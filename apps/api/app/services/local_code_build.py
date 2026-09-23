"""Persistent-CLI dispatch on the existing Build queue, not another executor."""
from datetime import datetime, timezone
import subprocess

from app.models.handoff import AgentBuildJob, AgentRun
from app.services import agent_lifecycle as lifecycle, build_jobs, local_code_channel as channel
from app.services import local_model
from app.services.handoff import add_run_event, build_context, update_run, HandoffError


def enqueue(db, run):
    existing = build_jobs.active_job(db, run.id)
    if existing:
        return existing
    if lifecycle.run_binding(channel.AGENT, run.id):
        raise HandoffError('Run já possui entrega persistida; reenvio recusado')
    job = build_jobs.open_job(db, run, runtime_id=channel.AGENT, model=run.model)
    add_run_event(db, run, 'build.cli_queued', 'Plano na fila da CLI local-code',
                  {'job_id': str(job.id), 'runtime_id': channel.AGENT, 'tmux_session': channel.SESSION})
    return job


def _event_payload(job, data):
    return dict(job_id=str(job.id), runtime_id=channel.AGENT, tmux_session=channel.SESSION,
                prompt_sha256=data['prompt_sha256'], pid=data['pid'], starttime=data['starttime'])


def dispatch(db, job, run):
    """The agent lock spans intent/transport/ack, never the life of the run."""
    try:
        with lifecycle.agent_lock(channel.AGENT, blocking=False):
            db.refresh(run, with_for_update=True)
            if run.status != 'queued':
                build_jobs.fail_job(db, job, error='Run não está aguardando; entrega recusada')
                db.commit()
                return None
            binding = lifecycle.run_binding(channel.AGENT, run.id)
            if binding:
                # Crash before DB commit: durable intent is enough to refuse replay.
                build_jobs.fail_job(db, job, error='Entrega anterior incerta; reconciliação necessária')
                db.commit()
                return None
            prompt = build_context(db, run)['prompt']
            from app.services.review_scope import capture_start_base
            capture_start_base(db, run)
            # Modelo físico real servido agora pelo llama.cpp (q4/q2/bonsai).
            # O alias estável workdev-qwen27b em run.model não muda; esta chave
            # registra qual peso respondeu a execução.
            run.local_model_key = local_model.current()
            data = channel.reserve(run.id, job.id, prompt)
            if data is None:
                db.rollback()  # BUSY/offline/manual: keep queued, release SKIP LOCKED claim.
                return None
            job.prompt_sha256 = data['prompt_sha256']
            job.payload = {'transport': 'persistent_cli', 'tmux_session': channel.SESSION}
            build_jobs.start_job(db, job)
            update_run(db, run, {'status': 'running', 'message': 'Plano reservado para a CLI local-code'})
            add_run_event(db, run, 'build.cli_delivery_requested', 'Entrega reservada na sessão canônica',
                          _event_payload(job, data))
            db.commit()  # Audit is durable BEFORE any terminal input.
            try:
                channel.send_marker(data)
                channel.wait_ack(run.id)
            except (lifecycle.LifecycleError, OSError, TimeoutError, subprocess.SubprocessError) as error:
                job.error = f'Entrega incerta: {type(error).__name__}; sem reenvio automático'
                add_run_event(db, run, 'build.cli_delivery_uncertain', job.error, _event_payload(job, data))
                db.commit()
                return None
            _ack(db, job, run, data)
            db.commit()
    except BlockingIOError:
        db.rollback()
    return None


def _ack(db, job, run, data):
    if not (job.payload or {}).get('acknowledged'):
        job.payload = {**(job.payload or {}), 'acknowledged': True}
        job.error = None
        add_run_event(db, run, 'build.cli_received', 'Qwen confirmou recebimento do plano',
                      _event_payload(job, data))


def reconcile(db):
    """Recover receipts after worker/API restart without replaying input."""
    try:
        with lifecycle.agent_lock(channel.AGENT, blocking=False):
            with channel.channel_lock():
                data = channel.read()
            if not data.get('run_id'):
                return
            from uuid import UUID
            run = db.get(AgentRun, UUID(data['run_id']))
            job = db.get(AgentBuildJob, UUID(data['job_id']))
            if not run or not job:
                return
            if job.state == 'done':
                channel.release(run.id)
                return
            if job.state != 'running':
                return
            if data.get('acknowledged'):
                _ack(db, job, run, data)
            if (run.status in {'review', 'completed', 'failed', 'cancelled'}
                    and data.get('phase') in {'turn_done', 'cancelled'}):
                # Commit finish first; release second. Recovery also handles done jobs.
                build_jobs.finish_job(db, job, payload={'cli_turn_finished': True})
                add_run_event(db, run, 'build.cli_released', 'Run liberou a sessão persistente',
                              _event_payload(job, data))
                db.commit()
                channel.release(run.id)
            else:
                db.commit()
    except BlockingIOError:
        db.rollback()


def cancel_queued(db, run):
    """Called under agent lock before taking database locks."""
    db.refresh(run, with_for_update=True)
    if run.status != 'queued' or lifecycle.run_binding(channel.AGENT, run.id):
        return False
    job = build_jobs.active_job(db, run.id)
    if job:
        job.state, job.finished_at = 'cancelled', datetime.now(timezone.utc)
    update_run(db, run, {'status': 'cancelled', 'message': 'Run retirada da fila; CLI preservada'})
    db.commit()
    return True
