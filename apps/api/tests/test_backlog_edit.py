"""Real HTTP routing and persistence on isolated SQLite, with FK enforcement.

Reuses the end-to-end handoff fixture (including its PostgreSQL clock adapter).
Does not connect to or mutate production PostgreSQL.
"""
from uuid import uuid4

import pytest
from sqlalchemy import select

from tests.test_backlog_ai_hub_flow import flow as flow  # noqa: F401
from app.models.backlog import BacklogItem
from app.models.chat import ChatSession, ChatMessage
from app.models.handoff import ExecutionPlan, AgentRun, AgentRunEvent
from app.models.subtask import BacklogSubtask


@pytest.fixture
def linked_task(flow):
    with flow.factory() as db:
        item = db.get(BacklogItem, flow.task_id)
        item.description = 'Descrição\nContexto\nEscopo'
        item.owner, item.sprint, item.effort, item.rank = 'Claudio', 'sprint-1', 3, 7
        plan = ExecutionPlan(id=uuid4(), backlog_id=item.id, version=1,
                             title='Plano aprovado', objective='Objetivo original', status='approved')
        session = ChatSession(id=uuid4(), task_id=item.id, project_id=item.project_id, title='Histórico')
        sub = BacklogSubtask(id=uuid4(), backlog_id=item.id, title='Subtask vinculada')
        db.add_all([plan, session, sub]); db.commit()
        run = AgentRun(id=uuid4(), backlog_id=item.id, plan_id=plan.id, agent='codex', status='running')
        db.add(run); db.commit()
        db.add_all([
            AgentRunEvent(id=uuid4(), run_id=run.id, event_type='build.started', message='Histórico original'),
            ChatMessage(id=uuid4(), session_id=session.id, role='user', content='Mensagem original'),
        ])
        db.commit()
    return flow


def snapshot(flow):
    with flow.factory() as db:
        return {
            model.__tablename__: [dict(row) for row in db.execute(select(model.__table__)).mappings()]
            for model in (BacklogItem, BacklogSubtask, ExecutionPlan, AgentRun, AgentRunEvent, ChatSession, ChatMessage)
        }


def test_patch_persists_edit_without_recreating_task_or_touching_links(linked_task):
    flow = linked_task
    before = snapshot(flow)
    changes = {'title': 'Título atualizado', 'description': 'Novo contexto\nNovo escopo',
               'priority': 'high', 'status': 'doing'}
    response = flow.client.patch(f'/api/backlog/{flow.task_id}', json=changes)
    assert response.status_code == 200, response.text
    assert response.json()['id'] == str(flow.task_id)
    assert all(response.json()[key] == value for key, value in changes.items())
    # Independent request/session proves it was committed, not just echoed.
    persisted = flow.client.get('/api/backlog').json()
    assert len(persisted) == 1
    assert persisted[0] == response.json()
    after = snapshot(flow)
    for table in before.keys() - {'backlog'}:
        assert after[table] == before[table], table
    old, new = before['backlog'][0], after['backlog'][0]
    for field in old.keys() - changes.keys() - {'updated_at'}:
        assert new[field] == old[field], field


def test_pending_subtasks_reject_entire_edit_and_preserve_history(linked_task):
    flow = linked_task
    before = snapshot(flow)
    response = flow.client.patch(f'/api/backlog/{flow.task_id}', json={'title': 'Não salvar', 'status': 'done'})
    assert response.status_code == 400
    assert response.json()['detail']['code'] == 'active_subtasks_remaining'
    assert 'Subtask vinculada' in response.json()['detail']['message']
    assert snapshot(flow) == before


def test_partial_patch_can_clear_description_and_preserve_other_fields(linked_task):
    flow = linked_task
    original = flow.client.get('/api/backlog').json()[0]
    response = flow.client.patch(f'/api/backlog/{flow.task_id}', json={'description': ''})
    assert response.status_code == 200
    assert response.json()['description'] == ''
    assert {k: v for k, v in response.json().items() if k not in ('description', 'updated_at')} == {
        k: v for k, v in original.items() if k not in ('description', 'updated_at')}


@pytest.mark.parametrize(('identifier', 'payload', 'status'), [
    (str(uuid4()), {'title': 'Inexistente'}, 404),
    ('invalid-uuid', {'title': 'Inválida'}, 422),
    (None, {'title': {'invalid': 'type'}}, 422),
])
def test_update_errors_do_not_modify_existing_task(linked_task, identifier, payload, status):
    flow = linked_task
    before = snapshot(flow)
    response = flow.client.patch(f'/api/backlog/{identifier or flow.task_id}', json=payload)
    assert response.status_code == status
    assert 'detail' in response.json()
    assert snapshot(flow) == before
