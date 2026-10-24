"""Backlog → chat → draft → human approval → queue → outcome, isolated DB.

SQLite exercises persistence and routing, not PostgreSQL row-lock scheduling.
The SQL lock contract is checked separately below.
"""
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import JSON, MetaData, create_engine, event, text, select, func
from sqlalchemy.dialects.postgresql import JSONB, dialect
from sqlalchemy.schema import DefaultClause
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import TextClause

from app.models.project import Project
from app.models.backlog import BacklogItem
from app.models.subtask import BacklogSubtask
from app.models.chat import ChatSession, ChatMessage
from app.models.handoff import ExecutionPlan, AgentRun, AgentRunEvent
from app.models.deployment import DeploymentOutcome
from app.routers import ai, backlog, chat_sessions, handoffs, deployments
from app.services import handoff


@pytest.fixture
def flow(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path}/flow.db', connect_args={'check_same_thread': False})
    @event.listens_for(engine, 'connect')
    def configure(conn, _record):
        conn.execute('PRAGMA foreign_keys=ON')
    metadata = MetaData()
    for model in (Project, BacklogItem, BacklogSubtask, ChatSession, ChatMessage,
                  ExecutionPlan, AgentRun, AgentRunEvent, DeploymentOutcome):
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
            if column.server_default is not None:
                value = str(column.server_default.arg)
                value = value.replace('gen_random_uuid()', '(lower(hex(randomblob(16))))')
                value = value.replace('now()', 'CURRENT_TIMESTAMP').replace('::jsonb', '')
                column.server_default = DefaultClause(text(value))
    metadata.create_all(engine)
    class SQLiteSession(Session):
        def execute(self, statement, *args, **kwargs):
            # PostgreSQL returns datetime for this raw SQL. SQLite needs its
            # native clock plus SQLAlchemy's datetime result conversion.
            if isinstance(statement, TextClause) and str(statement) == 'SELECT now()':
                statement = select(func.now())
            return super().execute(statement, *args, **kwargs)

    factory = sessionmaker(bind=engine, class_=SQLiteSession, expire_on_commit=False)
    with factory() as db:
        project = Project(id=uuid4(), name='Test Project', slug='test', type='web', status='active')
        db.add(project); db.commit()
        task = BacklogItem(id=uuid4(), project_id=project.id, title='Manual task', status='todo')
        db.add(task); db.commit()
        task_id = task.id
    def db_override():
        with factory() as db:
            yield db
    app = FastAPI()
    for router in (backlog.router, chat_sessions.router, handoffs.router, deployments.router):
        app.include_router(router, prefix='/api')
    for dependency in (backlog.get_db, chat_sessions.get_db, handoffs.get_db, deployments.get_db):
        app.dependency_overrides[dependency] = db_override
    monkeypatch.setattr(handoffs, '_sync_plan', lambda *args: None)
    monkeypatch.setattr(ai.graph_sync, 'sync_safely', lambda *args: None)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, factory=factory, task_id=task_id)
    engine.dispose()


def draft_payload(task_id):
    return {'backlog_id': str(task_id), 'objective': 'Add task entry',
            'acceptance_criteria': ['Task retains identity'], 'validation_steps': ['Exercise flow']}


def test_manual_task_keeps_identity_through_approval_queue_and_outcome(flow):
    client, task_id = flow.client, flow.task_id
    eligibility = client.get(f'/api/chat/sessions/from-task/{task_id}/eligibility').json()
    assert eligibility['eligible']
    response = client.post('/api/chat/sessions/from-task', json={'task_id': str(task_id)})
    assert response.status_code == 201, response.text
    session = response.json()
    assert session['backlog_id'] == str(task_id)
    restored = client.get(f"/api/chat/sessions/{session['id']}").json()
    assert restored['backlog_id'] == str(task_id)
    with flow.factory() as db:
        assert str(task_id) in db.query(ChatMessage).filter(ChatMessage.role == 'system').one().content
    assert client.post('/api/chat/sessions/from-task', json={'task_id': str(task_id)}).json()['id'] == session['id']
    with flow.factory() as db:
        assert db.query(ExecutionPlan).count() == db.query(AgentRun).count() == 0
    response = client.post('/api/handoffs/plans', json=draft_payload(task_id))
    assert response.status_code == 201, response.text
    plan_data = response.json()
    assert plan_data['backlog_id'] == str(task_id) and plan_data['status'] == 'draft'
    with flow.factory() as db:
        plan = db.query(ExecutionPlan).one()
        with pytest.raises(handoff.HandoffError, match='aprovado'):
            handoff.queue_build(db, plan, 'codex', reviewer='gemini')
        assert db.query(AgentRun).count() == 0
    approved = client.post(f"/api/handoffs/plans/{plan_data['id']}/approve")
    assert approved.status_code == 200, approved.text
    with flow.factory() as db:
        assert db.query(AgentRun).count() == 0  # Approval is not dispatch.
        plan = db.query(ExecutionPlan).one()
        run, queued = handoff.queue_build(db, plan, 'codex', reviewer='gemini')
        assert run.backlog_id == task_id and run.plan_id == plan.id
        assert queued.event_type == 'build.queued'
        run_id = str(run.id)
    response = client.post('/api/deployments/outcomes', json={
        'proof_id': 'test-proof', 'project': 'test', 'artifact_fingerprint': 'a' * 64,
        'outcome': 'success', 'agent_run_id': run_id, 'backlog_id': str(task_id),
        'postcheck_result': {'status': 'DEPLOY_SUCCEEDED'},
    })
    assert response.status_code == 201, response.text
    with flow.factory() as db:
        outcome = db.query(DeploymentOutcome).one()
        run = db.query(AgentRun).one()
        plan = db.query(ExecutionPlan).one()
        assert outcome.backlog_id == run.backlog_id == plan.backlog_id == task_id
        assert outcome.agent_run_id == run.id


@pytest.mark.parametrize('status', ['draft', 'needs_revision', 'approved'])
def test_active_plan_blocks_duplicate_session_and_plan(flow, status):
    response = flow.client.post('/api/handoffs/plans', json=draft_payload(flow.task_id))
    assert response.status_code == 201
    with flow.factory() as db:
        db.query(ExecutionPlan).one().status = status; db.commit()
    eligibility = flow.client.get(f'/api/chat/sessions/from-task/{flow.task_id}/eligibility').json()
    assert not eligibility['eligible']
    response = flow.client.post('/api/chat/sessions/from-task', json={'task_id': str(flow.task_id)})
    assert response.status_code == 409 and response.json()['detail']['code'] == 'active_plan_exists'
    assert flow.client.post('/api/handoffs/plans', json=draft_payload(flow.task_id)).status_code == 400
    with flow.factory() as db:
        assert db.query(ExecutionPlan).count() == 1
        assert db.query(AgentRun).count() == db.query(ChatSession).count() == 0


def test_completed_task_cannot_start_planning(flow):
    with flow.factory() as db:
        db.query(BacklogItem).one().status = 'done'; db.commit()
    assert not flow.client.get(f'/api/chat/sessions/from-task/{flow.task_id}/eligibility').json()['eligible']
    assert flow.client.post('/api/chat/sessions/from-task', json={'task_id': str(flow.task_id)}).status_code == 409


def test_bound_tool_fills_missing_id_and_rejects_other_task(flow):
    with flow.factory() as db:
        args = {'objetivo': 'Plan task', 'aprovado_pelo_usuario': True,
                'criterios_aceite': ['ok'], 'validacoes': ['test']}
        bad = json.loads(ai.executar_tool('criar_plano_execucao', {**args, 'task_id': str(uuid4())},
                         db, 'plan', backlog_id=flow.task_id))
        assert bad['code'] == 'backlog_context_mismatch'
        assert db.query(ExecutionPlan).count() == 0
        good = json.loads(ai.executar_tool('criar_plano_execucao', args, db, 'plan', backlog_id=flow.task_id))
        assert good['ok'] and good['task_id'] == str(flow.task_id)
        assert db.query(ExecutionPlan).one().backlog_id == flow.task_id
        assert db.query(AgentRun).count() == 0


def test_linked_chat_rejects_project_change(flow):
    data = flow.client.post('/api/chat/sessions/from-task', json={'task_id': str(flow.task_id)}).json()
    response = flow.client.patch(f"/api/chat/sessions/{data['id']}", json={'project_id': None})
    assert response.status_code == 409


def test_plan_creation_and_session_entry_lock_same_backlog_row(flow):
    # Compile the real queries emitted by both entry points with PG dialect.
    from sqlalchemy.orm import Query
    captured = []
    original = Query.with_for_update
    def capture(query, *args, **kwargs):
        locked = original(query, *args, **kwargs)
        captured.append(str(locked.statement.compile(dialect=dialect())))
        return locked
    from unittest.mock import patch
    with patch.object(Query, 'with_for_update', capture):
        flow.client.post('/api/chat/sessions/from-task', json={'task_id': str(flow.task_id)})
        flow.client.post('/api/handoffs/plans', json=draft_payload(flow.task_id))
    assert len(captured) == 2
    assert all('FROM backlog' in sql and 'FOR UPDATE' in sql for sql in captured)


@pytest.mark.parametrize(('provider', 'model', 'function'), [
    ('anthropic', 'claude-haiku-4-5', 'chat_anthropic'),
    ('openai', 'gpt-4o-mini', 'chat_openai'),
])
def test_chat_passes_persisted_task_to_provider(provider, model, function, monkeypatch):
    from unittest.mock import Mock
    task_id = uuid4()
    session = SimpleNamespace(id=uuid4(), task_id=task_id, project_id=uuid4(), authority='plan')
    db = Mock()
    db.query.return_value.filter.return_value.first.side_effect = [session, SimpleNamespace(slug='test')]
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        SimpleNamespace(content='Contexto da task de origem')]
    call = Mock(return_value='Prévia')
    monkeypatch.setattr(ai, function, call)
    monkeypatch.setattr(ai, 'build_system', lambda *args: 'Sistema')
    result = ai.ai_chat(ai.ChatRequest(session_id=str(session.id), provider=provider, model=model,
        messages=[{'role': 'user', 'content': 'Planejar'}]), db)
    assert not result.get('error'), result
    assert call.call_args.kwargs['backlog_id'] == task_id
    assert 'Contexto da task de origem' in call.call_args.kwargs['system']
    assert result['backlog_id'] == str(task_id)
