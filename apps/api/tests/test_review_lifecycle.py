"""Integração do ciclo de revisão por risco: PATCH review → decisão persistida.

Segue o padrão de test_workspace_http.py com mapeamento imperativo de tabelas
SQLite. Gate evidence é fabricada com obrigatórios completos (sha, backlog).
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import registry, sessionmaker

from app.auth import COOKIE_NAME, create_session_token
from app.main import app
from app.routers import handoffs
from app.services import handoff, review_cycle, review_package, test_gate


@pytest.fixture
def lifecycle_api(tmp_path, monkeypatch):
    mapping = registry()

    class Run: pass
    class Task: pass
    class Event: pass
    class Plan: pass
    class Cycle: pass
    class Review: pass

    mapping.map_imperatively(Run, Table('agent_runs', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True), Column('agent', String),
        Column('backlog_id', UUID(as_uuid=True)), Column('plan_id', UUID(as_uuid=True)),
        Column('status', String), Column('reviewer_agent', String),
        Column('model', String), Column('complexity', String), Column('commit_sha', String),
        Column('routing_mode', String), Column('summary', String),
        Column('result', String), Column('error', String),
        Column('started_at', DateTime), Column('finished_at', DateTime),
        Column('review_attempts', Integer, default=0),
        Column('created_at', DateTime, default=lambda: datetime.now(timezone.utc)),
        Column('updated_at', DateTime)))
    mapping.map_imperatively(Task, Table('backlog', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True), Column('title', String),
        Column('type', String), Column('status', String), Column('owner', String),
        Column('updated_at', DateTime)))
    subtasks = Table('backlog_subtasks', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
        Column('backlog_id', UUID(as_uuid=True)), Column('assigned_agent', String))
    mapping.map_imperatively(Event, Table('agent_run_events', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
        Column('run_id', UUID(as_uuid=True)), Column('event_type', String),
        Column('message', String), Column('payload', JSON, default={}),
        Column('created_at', DateTime, default=lambda: datetime.now(timezone.utc))))
    mapping.map_imperatively(Plan, Table('execution_plans', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True), Column('backlog_id', UUID(as_uuid=True)),
        Column('version', Integer, default=1), Column('status', String), Column('title', String),
        Column('objective', String), Column('scope', String),
        Column('constraints', JSON, default=[]),
        Column('acceptance_criteria', JSON, default=[]),
        Column('validation_steps', JSON, default=[]),
        Column('created_by', String, default='test'),
        Column('created_at', DateTime, default=lambda: datetime.now(timezone.utc)),
        Column('updated_at', DateTime)))
    mapping.map_imperatively(Review, Table('agent_run_reviews', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
        Column('run_id', UUID(as_uuid=True)), Column('attempt', Integer, default=1),
        Column('executor_agent', String), Column('reviewer_agent', String),
        Column('verdict', String), Column('feedback', String),
        Column('gate_passed', JSON),
        Column('payload', JSON, default={}),
        Column('created_at', DateTime, default=lambda: datetime.now(timezone.utc))))
    mapping.map_imperatively(Cycle, Table('review_cycles', mapping.metadata,
        Column('id', UUID(as_uuid=True), primary_key=True, default=uuid4),
        Column('run_id', UUID(as_uuid=True)), Column('attempt', Integer, default=1),
        Column('decision', String), Column('tier', String, default='none'),
        Column('task_risk', String), Column('agent_trust', String),
        Column('gate_result', String), Column('sensitive', JSON, default=[]),
        Column('justification', String),
        Column('diff_files', Integer, default=0), Column('diff_lines', Integer, default=0),
        Column('context_bytes', Integer, default=0),
        Column('tokens_estimate', Integer, default=0),
        Column('reviewer_agent', String), Column('verdict', String),
        Column('escalated', JSON, default=False),
        Column('duration_ms', Integer),
        Column('created_at', DateTime, default=lambda: datetime.now(timezone.utc)),
        Column('closed_at', DateTime)))

    metadata = MetaData()
    for table in mapping.metadata.tables.values():
        table.to_metadata(metadata)
    engine = create_engine(f'sqlite:///{tmp_path}/lifecycle.db')
    metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    monkeypatch.setattr(handoffs, '_sync_run', lambda *args: None)
    monkeypatch.setattr(handoffs, '_run_out', lambda db, row: {'id': str(row.id), 'agent': row.agent, 'status': row.status, 'reviewer_agent': row.reviewer_agent})
    monkeypatch.setattr(handoffs, 'SessionLocal', factory)
    for module in (review_cycle, review_package, handoffs, handoff):
        for attr, cls in [('AgentRun', Run), ('AgentRunEvent', Event), ('ReviewCycle', Cycle), ('AgentRunReview', Review),
                          ('BacklogItem', Task), ('ExecutionPlan', Plan)]:
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, cls)
    monkeypatch.setenv('WORKDEV_SESSION_SECRET', 'lifecycle-test-secret')

    with factory() as db:
        plan = Plan(); plan.id = uuid4(); plan.backlog_id = uuid4()
        plan.status = 'approved'; plan.title = 'Lifecycle'; plan.objective = 'Objetivo'
        run = Run(); run.id = uuid4(); run.plan_id = plan.id
        run.backlog_id = plan.backlog_id; run.agent = 'codex'; run.status = 'running'
        db.add_all([plan, run]); db.commit()
    client = TestClient(app)
    client.cookies.set(COOKIE_NAME, create_session_token())
    try:
        yield client, run.id, factory, Run, Event, Cycle
    finally:
        engine.dispose()


def add_evidence(db, Run, Event, run_id, passed=True, mandatory_failed=None):
    run = db.get(Run, run_id)
    kind = 'build.tests_passed' if passed else 'build.tests_failed'
    payload = {
        'run_id': str(run.id), 'backlog_id': str(run.backlog_id),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'git_commit_sha': test_gate._get_git_commit_sha(), 'passed': passed,
        'checks': [{'name': 'pytest', 'passed': passed, 'mandatory': True, 'reason': 'r', 'duration_ms': 1}],
        'mandatory_failed': mandatory_failed or [], 'error': None,
    }
    db.add(Event(run_id=run_id, event_type=kind, message='gate', payload=payload))
    db.commit()


def test_low_trusted_completes_sem_revisor_llm(lifecycle_api, monkeypatch):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    monkeypatch.setattr(review_cycle, 'collect_diff_stats', lambda *_: (['docs/x.md'], 'pequeno'))
    with factory() as db:
        add_evidence(db, Run, Event, run_id, passed=True)
    response = client.patch(f'/api/handoffs/runs/{run_id}', json={'status': 'review'})
    assert response.status_code == 200, response.text
    with factory() as db:
        run = db.query(Run).one()
        cycle = db.query(Cycle).one()
        assert run.status == 'completed'
        assert cycle.decision == 'NO_REVIEW_COMPLETE' and cycle.tier == 'none'


def test_high_sensitive_goes_to_strong_review_then_completes(lifecycle_api, monkeypatch):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    monkeypatch.setattr(review_cycle, 'collect_diff_stats', lambda *_: (['app/auth.py'], 'auth'))
    with factory() as db:
        db.query(Run).filter_by(id=run_id).update({'reviewer_agent': 'kimi', 'complexity': 'high'})
        db.commit()
        add_evidence(db, Run, Event, run_id, passed=True)
    response = client.patch(f'/api/handoffs/runs/{run_id}', json={'status': 'review'})
    assert response.status_code == 200, response.text
    with factory() as db:
        cycle = db.query(Cycle).one()
        run = db.query(Run).one()
        assert cycle.decision == 'REVISAR' and cycle.tier == 'strong'
        assert run.status == 'review'
    verdict = client.post(f'/api/handoffs/runs/{run_id}/reviews',
                          json={'reviewer': 'kimi', 'verdict': 'approved'})
    assert verdict.status_code == 201, verdict.text
    with factory() as db:
        assert db.query(Run).one().status == 'completed'


def test_gate_fail_decided_sem_revisor(lifecycle_api, monkeypatch):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    monkeypatch.setattr(review_cycle, 'collect_diff_stats', lambda *_: (['docs/x.md'], 'pequeno'))
    with factory() as db:
        add_evidence(db, Run, Event, run_id, passed=False)
    response = client.patch(f'/api/handoffs/runs/{run_id}', json={'status': 'review'})
    assert response.status_code == 409, response.text
    with factory() as db:
        cycle = db.query(Cycle).one()
        assert cycle.decision == 'NO_REVIEW_GATE_FAIL'


def test_operational_guardrails_become_blocked(lifecycle_api, monkeypatch):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    monkeypatch.setattr(review_cycle, 'collect_diff_stats', lambda *_: (['docs/x.md'], 'pequeno'))
    with factory() as db:
        add_evidence(db, Run, Event, run_id, passed=False, mandatory_failed=['guardrails'])
    response = client.patch(f'/api/handoffs/runs/{run_id}', json={'status': 'review'})
    assert response.status_code == 409, response.text
    with factory() as db:
        run = db.query(Run).one()
        assert run.status == 'blocked'
        assert db.query(Event).filter_by(event_type='build.operational_failure').one()


def test_economic_escalation_swaps_reviewer(lifecycle_api, monkeypatch):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    monkeypatch.setattr(review_cycle, 'collect_diff_stats', lambda *_: (['alembic/versions/x.py'], 'migration'))
    with factory() as db:
        db.query(Run).filter_by(id=run_id).update({'reviewer_agent': 'qwen'})
        db.commit()
        add_evidence(db, Run, Event, run_id, passed=True)
    response = client.patch(f'/api/handoffs/runs/{run_id}', json={'status': 'review'})
    assert response.status_code == 200, response.text
    with factory() as db:
        cycle = db.query(Cycle).one()
        assert cycle.tier == 'economic'
    verdict = client.post(f'/api/handoffs/runs/{run_id}/reviews',
                          json={'reviewer': 'qwen', 'verdict': 'rejected', 'feedback': 'ESCALATE: incerto'})
    assert verdict.status_code == 201, verdict.text
    with factory() as db:
        run = db.query(Run).one()
        cycle = db.query(Cycle).order_by(Cycle.attempt.desc()).first()
        assert run.reviewer_agent in ('codex', 'claude', 'kimi')
        assert cycle.escalated and cycle.duration_ms is not None


def test_review_context_package_minimo(lifecycle_api):
    client, run_id, factory, Run, Event, Cycle = lifecycle_api
    response = client.get(f'/api/handoffs/runs/{run_id}/review-context')
    assert response.status_code == 200, response.text
    package = response.json()
    assert set(package) >= {'objective', 'acceptance_criteria', 'executor_summary',
                            'files_changed', 'gate', 'decision', 'context_bytes'}
    assert package['expand_options'] == ['diff']
