"""Durable cooperative pause at boundaries controlled by WorkDev."""

from datetime import datetime, timezone
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.backlog import BacklogItem
from app.models.handoff import AgentRun, AgentRunEvent


class RunPaused(RuntimeError):
    pass


def _latest(db: Session, run_id):
    return (db.query(AgentRunEvent)
            .filter(AgentRunEvent.run_id == run_id,
                    AgentRunEvent.event_type.in_({'observer.pause', 'observer.resumed'}))
            .order_by(AgentRunEvent.created_at.desc(), AgentRunEvent.id.desc()).first())


def is_paused(db: Session, run_id) -> bool:
    latest = _latest(db, UUID(str(run_id)))
    return bool(latest and latest.event_type == 'observer.pause')


def active_pause(db: Session, run_id):
    latest = _latest(db, UUID(str(run_id)))
    if not latest or latest.event_type != 'observer.pause':
        return None
    return {'reason': latest.message, 'evidence': (latest.payload or {}).get('evidence', {}),
            'event_id': str(latest.id), 'created_at': latest.created_at}


def assert_run_can_continue(db: Session, run_id) -> AgentRun:
    """Check the canonical DB state before starting any new WorkDev work unit.

    Callers must check again at the final transport boundary if preparation
    commits or releases the transaction in between.
    """
    run = db.get(AgentRun, UUID(str(run_id)), populate_existing=True)
    if run is None:
        raise RunPaused('Run não encontrada; avanço recusado')
    if is_paused(db, run.id) or run.status not in {'queued', 'running'}:
        raise RunPaused(f'Run em {run.status}; avanço recusado até retomada explícita')
    return run


@contextmanager
def checked_work_unit(run_id):
    """Serialize a short external send with PAUSE's row lock."""
    from app.database import SessionLocal
    with SessionLocal() as db:
        run = (db.query(AgentRun).filter(AgentRun.id == UUID(str(run_id)))
               .with_for_update().one_or_none())
        if run is None:
            raise RunPaused('Run não encontrada; avanço recusado')
        assert_run_can_continue(db, run.id)
        try:
            yield
            db.commit()
        except BaseException:
            db.rollback()
            raise


@contextmanager
def run_checkpoint(run_id):
    """Check before a long stage without delaying persistence of a new PAUSE."""
    from app.database import SessionLocal
    with SessionLocal() as db:
        assert_run_can_continue(db, run_id)
    yield


def request_pause(db: Session, run_id, *, reason: str, evidence: dict) -> AgentRun:
    """Persist PAUSE and evidence atomically; never touches the workspace."""
    from app.services.agent_lifecycle import run_lock
    with run_lock(run_id):
        return _request_pause_locked(db, run_id, reason=reason, evidence=evidence)


def _request_pause_locked(db: Session, run_id, *, reason: str, evidence: dict) -> AgentRun:
    run = (db.query(AgentRun).filter(AgentRun.id == UUID(str(run_id)))
           .with_for_update().one())
    if run.status not in {'queued', 'running'} or is_paused(db, run.id):
        return run
    previous = run.status
    previous_error = run.error
    run.status = 'blocked'
    run.error = reason[:1000]
    run.updated_at = datetime.now(timezone.utc)
    task = db.get(BacklogItem, run.backlog_id)
    previous_task_status = task.status if task else None
    if task:
        task.status = 'blocked'
        task.updated_at = run.updated_at
    db.add(AgentRunEvent(run_id=run.id, event_type='observer.pause',
        message=reason[:1000], payload={'action': 'PAUSE', 'from_status': previous,
                                        'previous_error': previous_error,
                                        'previous_task_status': previous_task_status,
                                        'reason': reason[:1000], 'evidence': evidence}))
    db.commit()
    return run


def resume_paused_run(db: Session, run_id, *, actor: str, reason: str) -> AgentRun:
    """Only an explicit authenticated route may call this operation."""
    run = (db.query(AgentRun).filter(AgentRun.id == UUID(str(run_id)))
           .with_for_update().one())
    pause = _latest(db, run.id)
    if not pause or pause.event_type != 'observer.pause' or run.status != 'blocked':
        raise RunPaused('Run não possui PAUSE ativo')
    previous = (pause.payload or {}).get('from_status')
    if previous not in {'queued', 'running'}:
        raise RunPaused('Estado anterior ao PAUSE inválido')
    run.status = previous
    run.error = (pause.payload or {}).get('previous_error')
    run.updated_at = datetime.now(timezone.utc)
    task = db.get(BacklogItem, run.backlog_id)
    if task:
        task.status = (pause.payload or {}).get('previous_task_status') or (
            'doing' if previous == 'running' else 'todo')
        task.updated_at = run.updated_at
    db.add(AgentRunEvent(run_id=run.id, event_type='observer.resumed',
        message=reason[:1000], payload={'actor': actor, 'reason': reason[:1000],
                                        'pause_event_id': str(pause.id)}))
    db.commit()
    return run
