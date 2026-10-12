"""Estado archived do backlog (ADR 009), por HTTP real sobre SQLite isolado.

Reusa o fixture end-to-end do handoff. Não conecta nem altera o PostgreSQL de
produção.
"""
import json
from uuid import uuid4

import pytest

from tests.test_backlog_ai_hub_flow import flow as flow  # noqa: F401
from app.models.backlog import BacklogItem
from app.models.subtask import BacklogSubtask
from app.routers import ai


def ids(response):
    assert response.status_code == 200, response.text
    return {item['id'] for item in response.json()}


def archive(flow, **extra):
    payload = {'status': 'archived', 'archived_reason': 'obsoleta', **extra}
    return flow.client.patch(f'/api/backlog/{flow.task_id}', json=payload)


def test_archive_cycle_hides_from_default_read_and_unarchive_restores(flow):
    task = str(flow.task_id)
    response = archive(flow, archived_note='perdeu sentido')
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['status'] == 'archived'
    assert body['archived_reason'] == 'obsoleta: perdeu sentido'
    assert body['archived_at']

    assert task not in ids(flow.client.get('/api/backlog'))
    assert task not in ids(flow.client.get('/api/backlog/test'))
    assert task in ids(flow.client.get('/api/backlog', params={'include_archived': 'true'}))
    assert task in ids(flow.client.get('/api/backlog/test', params={'include_archived': 'true'}))
    assert task in ids(flow.client.get('/api/backlog', params={'status': 'archived'}))

    # Arquivar não apaga: o registro continua lá, com motivo e data.
    with flow.factory() as db:
        row = db.get(BacklogItem, flow.task_id)
        assert row is not None and row.archived_at is not None
        assert row.archived_reason == 'obsoleta: perdeu sentido'

    response = flow.client.patch(f'/api/backlog/{task}/status', params={'status': 'todo'})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'todo'
    assert response.json()['archived_at'] is None
    assert response.json()['archived_reason'] is None
    assert task in ids(flow.client.get('/api/backlog'))


def test_status_route_archives_with_reason_query(flow):
    response = flow.client.patch(f'/api/backlog/{flow.task_id}/status',
                                 params={'status': 'archived', 'reason': 'sem_destravamento'})
    assert response.status_code == 200, response.text
    assert response.json()['archived_reason'] == 'sem_destravamento'


@pytest.mark.parametrize('route', ['item', 'status'])
def test_invalid_status_is_rejected_in_error_format(flow, route):
    if route == 'item':
        response = flow.client.patch(f'/api/backlog/{flow.task_id}', json={'status': 'cancelado'})
    else:
        response = flow.client.patch(f'/api/backlog/{flow.task_id}/status', params={'status': 'cancelado'})
    assert response.status_code == 422
    detail = response.json()['detail']
    assert set(detail) == {'code', 'message', 'details'}
    assert detail['code'] == 'invalid_status'
    assert detail['details']['received'] == 'cancelado'
    with flow.factory() as db:
        assert db.get(BacklogItem, flow.task_id).status == 'todo'


def test_create_rejects_status_outside_domain_and_archived(flow):
    with flow.factory() as db:
        project_id = str(db.get(BacklogItem, flow.task_id).project_id)
    for status, code in (('cancelado', 'invalid_status'), ('archived', 'cannot_create_archived')):
        response = flow.client.post('/api/backlog', json={
            'project_id': project_id, 'title': 'Nova', 'status': status})
        assert response.status_code == 422
        assert response.json()['detail']['code'] == code


@pytest.mark.parametrize(('payload', 'code'), [
    ({'status': 'archived'}, 'archived_reason_required'),
    ({'status': 'archived', 'archived_reason': 'preguica'}, 'invalid_archived_reason'),
    ({'status': 'doing', 'archived_reason': 'obsoleta'}, 'archived_reason_without_archive'),
    ({'archived_reason': 'obsoleta'}, 'archived_reason_without_archive'),
])
def test_archive_requires_valid_reason(flow, payload, code):
    response = flow.client.patch(f'/api/backlog/{flow.task_id}', json=payload)
    assert response.status_code == 422
    assert response.json()['detail']['code'] == code
    with flow.factory() as db:
        row = db.get(BacklogItem, flow.task_id)
        assert (row.status, row.archived_at, row.archived_reason) == ('todo', None, None)


def test_unarchive_only_back_to_todo(flow):
    assert archive(flow).status_code == 200
    response = flow.client.patch(f'/api/backlog/{flow.task_id}', json={'status': 'doing'})
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'archived_must_return_to_todo'
    with flow.factory() as db:
        assert db.get(BacklogItem, flow.task_id).status == 'archived'


def test_pending_subtasks_block_done_but_not_archive(flow):
    with flow.factory() as db:
        db.add(BacklogSubtask(id=uuid4(), backlog_id=flow.task_id, title='Pendente'))
        db.commit()
    for route in ('item', 'status'):
        if route == 'item':
            response = flow.client.patch(f'/api/backlog/{flow.task_id}', json={'status': 'done'})
        else:
            response = flow.client.patch(f'/api/backlog/{flow.task_id}/status', params={'status': 'done'})
        assert response.status_code == 400
        assert response.json()['detail']['code'] == 'active_subtasks_remaining'
    response = archive(flow)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'archived'


def test_ai_tool_archives_with_reason_and_validates(flow):
    with flow.factory() as db:
        sem_motivo = json.loads(ai.executar_tool(
            'atualizar_task', {'titulo_task': 'Manual task', 'novo_status': 'archived'}, db))
        assert sem_motivo['code'] == 'archived_reason_required'
        invalido = json.loads(ai.executar_tool(
            'atualizar_task', {'titulo_task': 'Manual task', 'novo_status': 'feito'}, db))
        assert invalido['code'] == 'invalid_status'
        assert db.get(BacklogItem, flow.task_id).status == 'todo'

        ok = json.loads(ai.executar_tool('atualizar_task', {
            'titulo_task': 'Manual task', 'novo_status': 'archived',
            'motivo_arquivamento': 'concluida_fora'}, db))
        assert ok['ok'] is True and ok['alteracoes']['status'] == 'archived'

        listadas = json.loads(ai.executar_tool('listar_backlog', {}, db))
        assert str(flow.task_id) not in {i['id'] for i in listadas}
        arquivadas = json.loads(ai.executar_tool('listar_backlog', {'status': 'archived'}, db))
        assert str(flow.task_id) in {i['id'] for i in arquivadas}

    with flow.factory() as db:
        row = db.get(BacklogItem, flow.task_id)
        assert (row.status, row.archived_reason) == ('archived', 'concluida_fora')
        assert row.archived_at is not None


def test_ai_tool_archive_still_respects_conversation_authority(flow):
    with flow.factory() as db:
        result = json.loads(ai.executar_tool('atualizar_task', {
            'titulo_task': 'Manual task', 'novo_status': 'archived',
            'motivo_arquivamento': 'obsoleta'}, db, 'observe'))
        assert result['executado'] is False
        assert db.get(BacklogItem, flow.task_id).status == 'todo'
