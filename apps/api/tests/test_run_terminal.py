"""Run terminal WS/REST: auth barrier, interactive PTY round-trip, resize and
graceful reattach. Real Linux PTYs over a SQLite persistence stand-in."""
import json
import tempfile
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, create_engine, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import sessionmaker

import app.routers.run_terminal as run_terminal
import app.services.terminal_sessions as service
from app.auth import COOKIE_NAME, create_session_token
from app.main import app
from app.models.terminal_session import TerminalSession
from app.services.terminal_sessions import TerminalSessionManager, TerminalSessionError


@pytest.fixture
def api_terminal(tmp_path, monkeypatch):
    from sqlalchemy.orm import registry
    mapping = registry()
    table = Table('agent_runs', mapping.metadata, Column('id', UUID(as_uuid=True), primary_key=True))

    class Run:
        pass
    mapping.map_imperatively(Run, table)
    monkeypatch.setattr(service, 'AgentRun', Run)
    metadata = MetaData()
    table.to_metadata(metadata)
    TerminalSession.__table__.to_metadata(metadata)
    engine = create_engine(f'sqlite:///{tmp_path}/sessions.db')

    @event.listens_for(engine, 'connect')
    def foreign_keys(conn, _):
        conn.execute('PRAGMA foreign_keys=ON')
    metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(run_terminal, 'SessionLocal', factory)
    monkeypatch.setenv('WORKDEV_SESSION_SECRET', 'test-secret')
    with factory() as db:
        run = Run()
        run.id = uuid4()
        db.add(run)
        db.commit()
    # tmp_path do pytest é longo demais para o limite de 108 bytes do socket Unix.
    with tempfile.TemporaryDirectory(prefix='wdpty-') as root:
        monkeypatch.setenv('WORKDEV_TERMINAL_DIR', root)
        client = TestClient(app)
        client.cookies.set(COOKIE_NAME, create_session_token())
        yield client, run.id, factory, root
        with factory() as db:
            try:
                TerminalSessionManager(db, root).close(run.id)
            except TerminalSessionError:
                pass
    engine.dispose()


def read_until(ws, marker: str, limit: int = 500) -> bytes:
    data = b''
    for _ in range(limit):
        message = ws.receive()
        if message.get('bytes') is not None:
            data += message['bytes']
            if marker.encode() in data:
                return data
    raise AssertionError(f'marker {marker!r} not seen; tail: {data[-300:]!r}')


def send_input(ws, text: str) -> None:
    ws.send_text(json.dumps({'type': 'input', 'data': text}))


def test_websocket_rejects_unauthenticated(api_terminal):
    _, run_id, _, _ = api_terminal
    anonymous = TestClient(app)  # sem cookie de sessão
    with pytest.raises(Exception) as denied:
        with anonymous.websocket_connect(f'/ws/runs/{run_id}/terminal'):
            pass
    assert getattr(denied.value, 'code', None) == 1008


def test_websocket_unknown_run_is_refused(api_terminal):
    client, _, _, _ = api_terminal
    with pytest.raises(Exception) as denied:
        with client.websocket_connect(f'/ws/runs/{uuid4()}/terminal'):
            pass
    assert getattr(denied.value, 'code', None) == 1008


def test_rest_requires_authentication(api_terminal):
    _, run_id, _, _ = api_terminal
    anonymous = TestClient(app)
    assert anonymous.get(f'/api/runs/{run_id}/terminal').status_code == 401
    assert anonymous.post(f'/api/runs/{run_id}/terminal').status_code == 401
    assert anonymous.delete(f'/api/runs/{run_id}/terminal').status_code == 401


def test_rest_rejects_unknown_run(api_terminal):
    client, _, _, _ = api_terminal
    unknown = uuid4()
    assert client.post(f'/api/runs/{unknown}/terminal').status_code == 404
    assert client.get(f'/api/runs/{unknown}/terminal').status_code == 404


def test_rest_lifecycle_create_health_close(api_terminal):
    client, run_id, _, _ = api_terminal
    created = client.post(f'/api/runs/{run_id}/terminal')
    assert created.status_code == 200, created.json()
    assert created.json()['state'] == 'RUNNING'
    again = client.post(f'/api/runs/{run_id}/terminal')
    assert again.status_code == 200 and again.json()['id'] == created.json()['id']
    health = client.get(f'/api/runs/{run_id}/terminal')
    assert health.status_code == 200 and health.json()['state'] == 'RUNNING'
    closed = client.delete(f'/api/runs/{run_id}/terminal')
    assert closed.status_code == 200 and closed.json()['state'] == 'CLOSED'


def test_websocket_interactive_shell_round_trip(api_terminal):
    client, run_id, _, _ = api_terminal
    marker = f'WS_E2E_{uuid4().hex[:8]}'
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal') as ws:
        send_input(ws, f'printf "{marker}\\n"\n')
        output = read_until(ws, marker)
        assert marker.encode() in output


def test_websocket_resize_reaches_pty(api_terminal):
    client, run_id, _, _ = api_terminal
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal') as ws:
        ws.send_text(json.dumps({'type': 'resize', 'rows': 50, 'cols': 132}))
        send_input(ws, 'stty size\n')
        output = read_until(ws, '50 132')
        assert b'50 132' in output


def test_websocket_disconnect_keeps_pty_alive_for_reattach(api_terminal):
    client, run_id, _, _ = api_terminal
    first = f'FIRST_{uuid4().hex[:8]}'
    second = f'SECOND_{uuid4().hex[:8]}'
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal') as ws:
        send_input(ws, f'printf "{first}\\n"\n')
        read_until(ws, first)
    # Nova conexão: snapshot carrega o buffer retido e o shell continua vivo.
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal') as ws:
        output = read_until(ws, first)
        assert first.encode() in output
        send_input(ws, f'printf "{second}\\n"\n')
        output = read_until(ws, second)
        assert second.encode() in output


def test_terminal_survives_api_side_disconnect(api_terminal):
    """O worker/PTY não morre quando o cliente some (resiliência de rede)."""
    client, run_id, factory, _ = api_terminal
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal') as ws:
        send_input(ws, 'true\n')
        time.sleep(.2)
    with factory() as db:
        item = TerminalSessionManager(db).health(run_id)
        assert item.state == 'RUNNING'
