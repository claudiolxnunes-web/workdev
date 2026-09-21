"""Queue/worker receipts persisted to an isolated DB, with real file locks."""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import Column, DateTime, Integer, JSON, String, Table, create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import registry, sessionmaker

from app.services import build_jobs, build_worker, handoff, local_code_build as build
from app.services import local_code_channel as channel, agent_lifecycle as lifecycle
from tests.test_local_code_channel import cli, event, marker, finish  # noqa: F401


@pytest.fixture
def queue_db(tmp_path, monkeypatch):
    mapping = registry()
    class Run: pass
    class Job: pass
    class Event: pass
    mapping.map_imperatively(Run, Table('agent_runs', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True), Column('agent', String),
        Column('status', String), Column('model', String), Column('dispatch_state', String),
        Column('dispatch_attempts', Integer, default=0), Column('dispatch_token', UUID(as_uuid=True)),
        Column('last_dispatch_at', DateTime)))
    mapping.map_imperatively(Job, Table('agent_build_jobs', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
        Column('run_id', UUID(as_uuid=True)), Column('runtime_id', String), Column('model', String),
        Column('state', String), Column('attempt', Integer), Column('prompt_sha256', String),
        Column('payload', JSON), Column('error', String), Column('started_at', DateTime),
        Column('finished_at', DateTime), Column('created_at', DateTime, default=lambda: datetime.now(timezone.utc))))
    mapping.map_imperatively(Event, Table('agent_run_events', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
        Column('run_id', UUID(as_uuid=True)), Column('event_type', String),
        Column('message', String), Column('payload', JSON)))
    engine = create_engine(f'sqlite:///{tmp_path}/queue.db')
    mapping.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    for module in (build, build_jobs, build_worker):
        monkeypatch.setattr(module, 'AgentRun', Run)
        monkeypatch.setattr(module, 'AgentBuildJob', Job)
    monkeypatch.setattr(handoff, 'AgentRunEvent', Event)
    monkeypatch.setattr(build, 'build_context', lambda db, run: {'prompt': f'Plano aprovado {run.id}'})
    def update(db, run, data):
        run.status = data['status']
        return run, None
    monkeypatch.setattr(build, 'update_run', update)
    monkeypatch.setattr('app.services.review_scope.capture_start_base', lambda db, run: None)
    def new_run():
        with factory() as db:
            run = Run(id=uuid4(), agent='local-code', status='queued', model='workdev-qwen27b')
            db.add(run)
            db.commit()
            job = build.enqueue(db, run)
            db.commit()
            return run.id, job.id
    yield SimpleNamespace(factory=factory, Run=Run, Job=Job, Event=Event, new=new_run)
    engine.dispose()


def deliver_and_ack(data):
    event('UserPromptSubmit', prompt=marker(data))


def test_dispatch_audits_run_identity_and_queues_second(cli, queue_db, monkeypatch):
    monkeypatch.setattr(channel, 'send_marker', deliver_and_ack)
    first, job1 = queue_db.new()
    second, job2 = queue_db.new()
    with queue_db.factory() as db:
        assert build.enqueue(db, db.get(queue_db.Run, first)).id == job1
        build.dispatch(db, db.get(queue_db.Job, job1), db.get(queue_db.Run, first))
        build.dispatch(db, db.get(queue_db.Job, job2), db.get(queue_db.Run, second))
    with queue_db.factory() as db:
        assert db.get(queue_db.Run, first).status == 'running'
        assert db.get(queue_db.Run, second).status == 'queued'
        assert db.get(queue_db.Job, job2).state == 'queued'
        events = db.query(queue_db.Event).filter_by(run_id=first).all()
        assert [e.event_type for e in events] == ['build.cli_queued', 'build.cli_delivery_requested', 'build.cli_received']
        receipt = events[-1].payload
        assert receipt['tmux_session'] == 'local-code'
        assert receipt['prompt_sha256'] == channel.read()['prompt_sha256']
        # A browser close/API restart has no effect; a new DB session sees same owner.
        assert lifecycle.run_binding('local-code', first)['pid'] == 42


def test_worker_uses_cli_and_never_http_for_local_code(cli, queue_db, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, Mock
    http = AsyncMock()
    execute = Mock()
    monkeypatch.setattr(build_worker, 'dispatch_to_llamacpp', http)
    monkeypatch.setattr(build_worker, 'dispatch_to_ollama', http)
    monkeypatch.setattr(build_worker, 'execute_build', execute)
    monkeypatch.setattr(channel, 'send_marker', deliver_and_ack)
    run_id, job_id = queue_db.new()
    with queue_db.factory() as db:
        asyncio.run(build_worker.process_job(db, db.get(queue_db.Job, job_id)))
    http.assert_not_awaited()
    execute.assert_not_called()
    assert channel.read()['run_id'] == str(run_id)


def test_restart_recovers_receipt_without_redelivery(cli, queue_db, monkeypatch):
    run_id, job_id = queue_db.new()
    def accepted_then_timeout(data):
        deliver_and_ack(data)
        raise lifecycle.LifecycleError('lost_reply', 'Worker lost receipt')
    monkeypatch.setattr(channel, 'send_marker', accepted_then_timeout)
    with queue_db.factory() as db:
        build.dispatch(db, db.get(queue_db.Job, job_id), db.get(queue_db.Run, run_id))
    monkeypatch.setattr(channel, 'send_marker', lambda _: pytest.fail('Replay after restart'))
    with queue_db.factory() as db:
        build.reconcile(db)
        job = db.get(queue_db.Job, job_id)
        assert job.payload['acknowledged']
        assert job.error is None
        assert db.query(queue_db.Event).filter_by(event_type='build.cli_received', run_id=run_id).count() == 1
        build.reconcile(db)
        assert db.query(queue_db.Event).filter_by(event_type='build.cli_received', run_id=run_id).count() == 1


def test_release_requires_both_turn_end_and_workflow(cli, queue_db, monkeypatch):
    monkeypatch.setattr(channel, 'send_marker', deliver_and_ack)
    run_id, job_id = queue_db.new()
    with queue_db.factory() as db:
        build.dispatch(db, db.get(queue_db.Job, job_id), db.get(queue_db.Run, run_id))
        run = db.get(queue_db.Run, run_id)
        run.status = 'review'
        db.commit()
        build.reconcile(db)
        assert channel.read()['run_id'] == str(run_id)
        finish()
        build.reconcile(db)
        assert channel.read()['phase'] == 'idle'
        assert db.get(queue_db.Job, job_id).state == 'done'


def test_cancel_queued_never_touches_cli(cli, queue_db):
    run_id, job_id = queue_db.new()
    with queue_db.factory() as db, lifecycle.agent_lock('local-code'):
        assert build.cancel_queued(db, db.get(queue_db.Run, run_id))
        assert db.get(queue_db.Job, job_id).state == 'cancelled'
    assert channel.read()['phase'] == 'idle'


def test_lost_cli_retains_queue(cli, queue_db, monkeypatch):
    monkeypatch.setattr(lifecycle, 'session_exists', lambda _: False)
    run_id, job_id = queue_db.new()
    with queue_db.factory() as db:
        build.dispatch(db, db.get(queue_db.Job, job_id), db.get(queue_db.Run, run_id))
        assert db.get(queue_db.Job, job_id).state == 'queued'
        assert db.get(queue_db.Run, run_id).status == 'queued'


def test_dispatch_route_queues_without_http_or_background(queue_db, monkeypatch):
    from unittest.mock import Mock
    from app.routers import handoffs
    run_id, job_id = queue_db.new()
    background = Mock()
    http = Mock(side_effect=AssertionError('HTTP path used'))
    monkeypatch.setattr(handoffs, 'ensure_dispatchable_blocking', http)
    monkeypatch.setattr(handoffs, '_run_out', lambda db, run: {'id': str(run.id)})
    monkeypatch.setattr(build_jobs, 'job_out', lambda job: {'id': str(job.id)})
    with queue_db.factory() as db:
        run = db.get(queue_db.Run, run_id)
        monkeypatch.setattr(handoffs, '_get_run', lambda db, key: run)
        response = handoffs.dispatch_run_to_ollama(run_id, background, db)
    assert response['dispatch']['id'] == str(job_id)
    background.add_task.assert_not_called()
    http.assert_not_called()


def test_claim_skips_unavailable_local_without_disabling_http(cli, monkeypatch):
    from types import SimpleNamespace
    event('UserPromptSubmit', prompt='trabalho manual')
    monkeypatch.setattr(build_worker, 'build_enabled', lambda: True)
    seen = {}
    class DB:
        def execute(self, sql, params):
            seen.update(params)
            return SimpleNamespace(first=lambda: None)
    build_worker.claim_next_job(DB())
    assert seen == {'http_enabled': True, 'local_ready': False}
