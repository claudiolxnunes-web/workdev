"""Workspace projections and audited actions over existing authorities."""
from app.database import SessionLocal
from app.models.backlog import BacklogItem
from app.models.handoff import AgentRun, AgentRunEvent
from app.models.terminal_session import TerminalSession
from app.services import agent_lifecycle
from app.services.handoff import RUN_TRANSITIONS, HandoffError, update_run
from app.services.terminal_sessions import TerminalSessionManager, TerminalSessionError


def audit(action, *, agent, run_id=None, result='requested', code=None):
    # Auth is enforced by the application. Existing shared cookie/API key does
    # not identify an individual human; never invent an actor name.
    with SessionLocal() as db:
        db.add(AgentRunEvent(run_id=run_id, event_type=f'workspace.{action}',
                            payload={'agent': agent, 'result': result, 'code': code,
                                     'actor': 'authenticated_operator'}))
        db.commit()


def enrich(snapshot, db):
    """Cheap projection: exactly the supplied snapshot, no physical probes."""
    rows = db.query(AgentRun, BacklogItem.title).join(
        BacklogItem, BacklogItem.id == AgentRun.backlog_id
    ).filter(AgentRun.status.in_(['queued', 'running', 'blocked', 'review'])).order_by(
        AgentRun.created_at.desc(), AgentRun.id
    ).all()
    by_agent = {row['agent']: [] for row in snapshot['agents']}
    for run, title in rows:
        if run.agent in by_agent:
            by_agent[run.agent].append(dict(id=str(run.id), agent=run.agent,
                backlog_id=str(run.backlog_id), task_title=title, status=run.status))
    agents = []
    for source in snapshot['agents']:
        row = {**source, 'runs': by_agent[source['agent']]}
        active_id = row.get('active_run_id')
        if active_id and active_id not in {run['id'] for run in row['runs']}:
            row.update(runtime_state='ERROR', reason='run_snapshot_mismatch',
                       health='degraded', health_reason='Associação da Run divergente do snapshot')
        agents.append(row)
    return {**snapshot, 'agents': agents}


def stop_run(db, run):
    """Validate → audit intent → stop physical work → persist cancelled.

    Shared file lock serializes launch/stop across API workers. The manager uses
    its own DB session, so its commits cannot release the workflow transaction.
    """
    with agent_lifecycle.run_lock(run.id):
        db.refresh(run, with_for_update={'key_share': True})
        if run.status == 'cancelled':
            binding = agent_lifecycle.run_binding(run.agent, run.id)
            if binding and binding.get('stopped'):
                db.rollback()
                return run
        if run.status != 'cancelled' and 'cancelled' not in RUN_TRANSITIONS.get(run.status, set()):
            raise HandoffError(f'Transição inválida: {run.status} → cancelled')
        audit('stop_run', agent=run.agent, run_id=run.id)
        try:
            agent_lifecycle.stop_run_process(run.agent, run.id)
            with SessionLocal() as terminal_db:
                terminal = terminal_db.query(TerminalSession).filter_by(run_id=run.id).first()
                if terminal:
                    item = TerminalSessionManager(terminal_db).close(run.id)
                    if item.state != 'CLOSED':
                        raise TerminalSessionError('Terminal cleanup incomplete')
            # Same validator/gates as other workflow transitions, never a second machine.
            run, _ = update_run(db, run, {'status': 'cancelled', 'message': 'Parada física confirmada pelo Workspace'})
            audit('stop_run', agent=run.agent, run_id=run.id, result='succeeded')
            return run
        except Exception as error:
            db.rollback()
            audit('stop_run', agent=run.agent, run_id=run.id, result='failed',
                  code=getattr(error, 'code', type(error).__name__))
            raise
