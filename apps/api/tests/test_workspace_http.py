"""HTTP + durable events + actual Run validator against isolated SQLite."""
from datetime import datetime, timezone
from uuid import uuid4
import json
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, DateTime, JSON, MetaData, String, Table, create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import registry, sessionmaker

from app.auth import COOKIE_NAME, create_session_token
from app.main import app
from app.models.terminal_session import TerminalSession
from app.routers import handoffs, terminal, run_terminal
from app.services import handoff, agent_workspace as workspace, agent_lifecycle as lifecycle, terminal_sessions


@pytest.fixture
def workspace_api(tmp_path, monkeypatch):
    mapping = registry()
    class Run: pass
    class Task: pass
    class Event: pass
    mapping.map_imperatively(Run, Table('agent_runs', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True), Column('agent', String),
        Column('backlog_id', UUID(as_uuid=True)), Column('status', String),
        Column('started_at', DateTime), Column('finished_at', DateTime),
        Column('created_at', DateTime, default=lambda: datetime.now(timezone.utc)),
        Column('updated_at', DateTime)))
    mapping.map_imperatively(Task, Table('backlog', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True), Column('title', String),
        Column('status', String), Column('owner', String), Column('updated_at', DateTime)))
    mapping.map_imperatively(Event, Table('agent_run_events', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
        Column('run_id', UUID(as_uuid=True)), Column('event_type', String),
        Column('message', String), Column('payload', JSON)))
    metadata = MetaData()
    for table in mapping.metadata.tables.values(): table.to_metadata(metadata)
    TerminalSession.__table__.to_metadata(metadata)
    engine = create_engine(f'sqlite:///{tmp_path}/workspace.db')
    metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    for module in (workspace, terminal, run_terminal):
        monkeypatch.setattr(module, 'SessionLocal', factory)
    for module in (workspace, handoffs, run_terminal, terminal_sessions):
        monkeypatch.setattr(module, 'AgentRun', Run)
    for module in (workspace, handoff):
        monkeypatch.setattr(module, 'AgentRunEvent', Event)
        monkeypatch.setattr(module, 'BacklogItem', Task)
    monkeypatch.setattr(handoffs, '_sync_run', lambda *args: None)
    monkeypatch.setattr(handoffs, '_run_out', lambda db, row: {'id':str(row.id), 'agent':row.agent, 'status':row.status})
    def db_override():
        with factory() as db: yield db
    app.dependency_overrides[handoffs.get_db] = db_override
    monkeypatch.setenv('WORKDEV_SESSION_SECRET', 'workspace-test-secret')
    monkeypatch.setattr(lifecycle, 'GROUPS_FILE', tmp_path / 'groups.json')
    with factory() as db:
        run = Run(); run.id=uuid4(); run.agent='kimi'; run.status='running'; run.backlog_id=uuid4()
        task=Task(); task.id=run.backlog_id; task.title='Workspace E2E'; task.status='doing'
        db.add_all([run,task]); db.commit()
    client=TestClient(app)
    client.cookies.set(COOKIE_NAME, create_session_token())
    yield client, run.id, factory, Run, Event
    app.dependency_overrides.pop(handoffs.get_db, None)
    engine.dispose()


def test_http_stop_real_process_persists_cancel_and_audit(workspace_api):
    client, run_id, factory, Run, Event = workspace_api
    process = subprocess.Popen(['sleep','120'], start_new_session=True)
    try:
        lifecycle.bind_run_process('kimi', run_id, process.pid)
        # Popen owns/reaps the child independently, as a real headless launcher does.
        import threading
        waiter=threading.Thread(target=process.wait)
        waiter.start()
        response=client.patch(f'/api/handoffs/runs/{run_id}', json={'status':'cancelled'})
        assert response.status_code==200, response.text
        waiter.join(timeout=3)
        assert process.poll() is not None
        assert response.json()['status']=='cancelled'
        assert client.patch(f'/api/handoffs/runs/{run_id}', json={'status':'cancelled'}).status_code==200
        with factory() as db:
            assert db.get(Run,run_id).status=='cancelled'
            events=db.query(Event).all()
            assert [e.payload['result'] for e in events if e.event_type=='workspace.stop_run']==['requested','succeeded']
            assert any(e.event_type=='build.cancelled' for e in events)
    finally:
        if process.poll() is None: process.terminate(); process.wait()


def test_http_unbound_run_is_not_cancelled_and_failure_is_durable(workspace_api):
    client, run_id, factory, Run, Event=workspace_api
    response=client.patch(f'/api/handoffs/runs/{run_id}', json={'status':'cancelled'})
    assert response.status_code==409
    assert response.json()['detail']['code']=='run_unbound'
    with factory() as db:
        assert db.get(Run,run_id).status=='running'
        assert any(e.payload.get('result')=='failed' for e in db.query(Event).all())
