import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from app.auth import COOKIE_NAME, create_session_token
from app.main import app
from app.reporting_security import project_public
from app.services import reporting

READ = 'readonly-test-credential-' + 'a' * 32
FULL = 'full-test-credential-' + 'b' * 32
START = datetime(2026, 9, 1, tzinfo=timezone.utc)
END = datetime(2026, 9, 8, tzinfo=timezone.utc)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('WORKDEV_READONLY_API_KEY', READ)
    monkeypatch.setenv('WORKDEV_API_KEY', FULL)
    monkeypatch.setenv('WORKDEV_SESSION_SECRET', 'reporting-test-session')
    return TestClient(app)


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
@pytest.mark.parametrize('path', ['/api/backlog', '/api/handoffs/runs/00000000-0000-0000-0000-000000000000/dispatch', '/api/auth/login'])
def test_readonly_denies_mutations_even_with_full_cookie(client, method, path):
    client.cookies.set(COOKIE_NAME, create_session_token())
    assert client.request(method, path, headers={'X-API-Key': READ}).status_code == 403


@pytest.mark.parametrize('path', ['/api/settings', '/api/settings/keys', '/api/terminal/codex',
    '/api/handoffs/runs/00000000-0000-0000-0000-000000000000/context',
    '/api/metrics/executive/cache', '/api/database', '/api/auth/me', '/api/backlog/foo/bar'])
def test_readonly_denies_sensitive_routes(client, path):
    assert client.get(path, headers={'X-API-Key': READ}).status_code == 403


def test_invalid_and_missing_credentials(client):
    for headers in [{}, {'X-API-Key': 'invalid'}]:
        assert client.get('/api/reporting/weekly-status', headers=headers).status_code == 401


def test_websocket_denied_even_with_cookie(client):
    from starlette.testclient import WebSocketDenialResponse
    client.cookies.set(COOKIE_NAME, create_session_token())
    with pytest.raises(WebSocketDenialResponse) as error:
        with client.websocket_connect('/api/terminal/codex/ws', headers={'X-API-Key': READ}):
            pass
    assert error.value.status_code == 403


def test_readonly_report_audited_without_secrets(client, monkeypatch, caplog):
    from app.routers import reporting as route
    monkeypatch.setattr(route, 'collect_weekly', lambda a, b: {'status': 'available', 'title': READ})
    with caplog.at_level('INFO', logger='workdev.reporting.audit'):
        r = client.get('/api/reporting/weekly-status', params={'since': START.isoformat(), 'until': END.isoformat()}, headers={'X-API-Key': READ})
    assert r.status_code == 200
    assert r.json()['title'] == '[REDACTED]'
    assert 'identity=reporting' in caplog.text and 'status=200' in caplog.text
    assert READ not in caplog.text and FULL not in caplog.text


def test_full_key_retains_existing_access(client, monkeypatch):
    from app.routers import reporting as route
    monkeypatch.setattr(route, 'collect_weekly', lambda a, b: {'status': 'available'})
    assert client.get('/api/reporting/weekly-status', params={'since': START.isoformat(), 'until': END.isoformat()}, headers={'X-API-Key': FULL}).status_code == 200


@pytest.mark.parametrize('since,until', [('2026-09-01', '2026-09-02'),
    ('2026-09-08T00:00:00Z', '2026-09-01T00:00:00Z'),
    ('2026-07-01T00:00:00Z', '2026-09-01T00:00:00Z'),
    ('2099-01-01T00:00:00Z', '2099-01-02T00:00:00Z')])
def test_invalid_interval(client, since, until):
    assert client.get('/api/reporting/weekly-status', params={'since': since, 'until': until}, headers={'X-API-Key': READ}).status_code == 422


def test_public_projection_removes_raw_context_and_credentials(monkeypatch):
    monkeypatch.setenv('WORKDEV_API_KEY', FULL)
    data = project_public({'id': '1', 'title': FULL, 'result': 'raw prompt',
                           'description': 'sensitive', 'payload': {'token': 'secret'},
                           'items': [{'id': '2', 'implementation_notes': 'raw'}]})
    assert data == {'id': '1', 'title': '[REDACTED]', 'items': [{'id': '2'}]}


def seed_supervisor(path, runs=None):
    path.mkdir()
    (path / 'state.json').write_text(json.dumps({'versao': 1, 'atualizado_em': END.isoformat(), 'achados': {}}))
    (path / 'runs.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in (runs or [])))


def test_supervisor_interval_and_no_writes(tmp_path):
    path = tmp_path / 'supervisor'
    records = [{'started_at': d, 'new_findings': n, 'worsened_findings': 2, 'resolved_findings': 1}
               for d, n in [('2026-09-01T00:00:00Z', 3), ('2026-09-08T00:00:00Z', 90)]]
    seed_supervisor(path, records)
    before = {p.name: p.read_bytes() for p in path.iterdir()}
    result = reporting.supervisor_report(path, START, END)
    assert result['counts'] == {'new_findings': 3, 'worsened_findings': 2, 'resolved_findings': 1}
    assert len(result['runs']) == 1
    assert before == {p.name: p.read_bytes() for p in path.iterdir()}
    assert reporting.supervisor_report(tmp_path / 'absent', START, END)['status'] == 'unavailable'


@pytest.fixture
def sources(monkeypatch, tmp_path):
    for name in ('main', 'quality'):
        seed_supervisor(tmp_path / name)
    monkeypatch.setattr(reporting, 'SUPERVISORS', {n: tmp_path / n for n in ('main', 'quality')})
    from app.services import agent_snapshot
    monkeypatch.setattr(agent_snapshot, 'read_snapshot', lambda ids: {'updated_at': END.isoformat(), 'agents': []})
    from app.routers import monitoring, deployments
    monkeypatch.setattr(monitoring, 'status', lambda: {'services': []})
    monkeypatch.setattr(deployments, 'deployment_status', lambda: {'apps': []})
    values = {name: [] for name in reporting.QUERIES}
    monkeypatch.setattr(reporting, 'query_source', lambda name, start, end: values[name])
    return values


def test_empty_period_is_no_news(sources):
    result = reporting.collect_weekly(START, END)
    assert result['no_news'] is True
    assert result['message'] == 'Sem novidades no intervalo.'
    assert result['dora']['lead_time_for_changes_hours'] is None


def test_interval_progress_current_pending_and_dora(sources):
    sources['backlog'] = [
        {'id': 'done', 'status': 'done', 'priority': 'medium', 'title': 'done', 'created_at': START, 'updated_at': START},
        {'id': 'pending', 'status': 'todo', 'priority': 'critical', 'title': 'next', 'created_at': END, 'updated_at': END}]
    sources['deployments'] = [{'id': 'deploy1', 'outcome': 'success'}, {'id': 'deploy2', 'outcome': 'degraded'}]
    result = reporting.collect_weekly(START, END)
    assert [r['id'] for r in result['progress']['created']] == ['done']
    assert [r['id'] for r in result['priority_pending']] == ['pending']
    assert result['dora']['deployment_frequency_per_week'] == 2
    assert result['dora']['change_failure_rate_percent'] == 50
    assert result['no_news'] is False


def test_source_failure_never_claims_no_news_or_exposes_exception(sources, monkeypatch):
    original = reporting.query_source
    def fail(name, start, end):
        if name == 'deployments':
            raise RuntimeError('postgres://password-do-not-leak')
        return original(name, start, end)
    monkeypatch.setattr(reporting, 'query_source', fail)
    result = reporting.collect_weekly(START, END)
    assert result['status'] == 'partial'
    assert not result['no_news']
    assert result['dora']['deployment_frequency_per_week'] is None
    assert 'password-do-not-leak' not in str(result)


def test_sql_sources_are_readonly_and_bounded(monkeypatch):
    db = MagicMock()
    db.execute.return_value.mappings.return_value.all.return_value = []
    factory = MagicMock()
    factory.return_value.__enter__.return_value = db
    monkeypatch.setattr(reporting, 'SessionLocal', factory)
    for name in reporting.QUERIES:
        reporting.query_source(name, START, END)
    statements = [str(c.args[0]) for c in db.execute.call_args_list]
    assert statements.count('SET TRANSACTION READ ONLY') == len(reporting.QUERIES)
    assert all(' LIMIT :limit' in q for q in statements if q.startswith('SELECT'))
    db.commit.assert_not_called()


def test_audit_route_never_logs_secret_in_path():
    from app.reporting_security import audit_route
    assert audit_route('/api/backlog/' + READ) == '/api/backlog/{id}'
    assert audit_route('/api/settings/' + READ) == '[forbidden]'


@pytest.mark.parametrize('keys', [(READ, 'invalid'), ('invalid', READ), (READ, FULL), (FULL, READ)])
def test_duplicate_headers_cannot_escalate_readonly(client, keys):
    client.cookies.set(COOKIE_NAME, create_session_token())
    headers = [('X-API-Key', key) for key in keys]
    assert client.post('/api/backlog', headers=headers, json={}).status_code == 403


def test_auth_helper_also_rejects_readonly_writes(monkeypatch):
    from starlette.requests import Request
    from app.auth import request_is_authenticated
    monkeypatch.setenv('WORKDEV_READONLY_API_KEY', READ)
    request = Request({'type': 'http', 'method': 'POST', 'path': '/api/backlog',
                       'headers': [(b'x-api-key', READ.encode())]})
    assert request_is_authenticated(request) is False
