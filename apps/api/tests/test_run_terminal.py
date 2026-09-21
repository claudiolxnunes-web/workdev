"""Run terminal WS/REST: auth barrier, interactive PTY round-trip, resize and
graceful reattach. Real Linux PTYs over a SQLite persistence stand-in."""
import json
import tempfile
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, String, create_engine, event
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
    # Audit persistence has its own HTTP integration fixture.
    monkeypatch.setattr('app.services.agent_workspace.audit', lambda *args, **kwargs: None)
    monkeypatch.setattr('app.services.agent_lifecycle.GROUPS_FILE', tmp_path / 'groups.json')
    from sqlalchemy.orm import registry
    mapping = registry()
    table = Table('agent_runs', mapping.metadata, Column('id', UUID(as_uuid=True), primary_key=True), Column('status', String, default='running'))

    class Run:
        pass
    mapping.map_imperatively(Run, table)
    monkeypatch.setattr(service, 'AgentRun', Run)
    monkeypatch.setattr(run_terminal, 'AgentRun', Run)
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


def test_status_and_reconnect_do_not_require_chat_tables(api_terminal):
    import base64
    from sqlalchemy import text
    client, run_id, factory, _ = api_terminal
    client.post(f'/api/runs/{run_id}/terminal')
    with factory() as db:
        # Simulate removing an independent chat lifecycle; no terminal FK points there.
        db.execute(text('CREATE TABLE chat_sessions (id integer PRIMARY KEY)'))
        db.execute(text('CREATE TABLE chat_messages (id integer PRIMARY KEY)'))
        db.execute(text('DROP TABLE chat_messages'))
        db.execute(text('DROP TABLE chat_sessions'))
        db.commit()
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal?existing=1') as ws:
        marker = f'RETAINED_{uuid4().hex[:8]}'
        send_input(ws, f'printf "{marker}\\n"\n')
        read_until(ws, marker)
    response = client.post(f'/api/runs/{run_id}/terminal/reconnect')
    assert response.status_code == 200
    state = response.json()
    assert state['run'] == {'id': str(run_id), 'status': 'running'}
    assert state['process']['alive'] and state['pty']['available']
    assert marker.encode() in base64.b64decode(state['buffer']['data'])
    assert state['websocket_url'].endswith('?existing=1')


def test_missing_recovery_never_creates_session(api_terminal, monkeypatch):
    client, run_id, factory, _ = api_terminal
    def forbidden(*args):
        pytest.fail('Recovery must not call create')
    monkeypatch.setattr(TerminalSessionManager, 'create', forbidden)
    assert client.post(f'/api/runs/{run_id}/terminal/reconnect').status_code == 404
    with pytest.raises(Exception) as denied:
        with client.websocket_connect(f'/ws/runs/{run_id}/terminal?existing=1'):
            pass
    assert getattr(denied.value, 'code', None) == 1008
    with factory() as db:
        assert db.query(TerminalSession).count() == 0


def test_multiple_clients_recover_same_process(api_terminal, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    client, run_id, factory, _ = api_terminal
    original = client.post(f'/api/runs/{run_id}/terminal').json()
    def forbidden(*args):
        pytest.fail('Recovery must not call create')
    monkeypatch.setattr(TerminalSessionManager, 'create', forbidden)
    with ThreadPoolExecutor(max_workers=4) as pool:
        states = list(pool.map(lambda _: client.post(f'/api/runs/{run_id}/terminal/reconnect').json(), range(8)))
    assert all(s['pid'] == original['pid'] and s['id'] == original['id'] for s in states)
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal?existing=1') as one:
        with client.websocket_connect(f'/ws/runs/{run_id}/terminal?existing=1') as two:
            marker = f'MULTI_{uuid4().hex[:8]}'
            send_input(one, f'printf "{marker}\\n"\n')
            assert marker.encode() in read_until(one, marker)
            assert marker.encode() in read_until(two, marker)
    with factory() as db:
        assert db.query(TerminalSession).count() == 1
        assert TerminalSessionManager(db).health(run_id).pid == original['pid']


def test_ended_process_is_not_resurrected(api_terminal, monkeypatch):
    client, run_id, factory, _ = api_terminal
    original = client.post(f'/api/runs/{run_id}/terminal').json()
    client.delete(f'/api/runs/{run_id}/terminal')
    monkeypatch.setattr(TerminalSessionManager, 'create', lambda *args: pytest.fail('No resurrection'))
    result = client.post(f'/api/runs/{run_id}/terminal/reconnect')
    assert result.status_code == 409 and result.json()['detail']['state'] == 'CLOSED'
    assert not result.json()['detail']['pty']['available']
    with pytest.raises(Exception) as denied:
        with client.websocket_connect(f'/ws/runs/{run_id}/terminal?existing=1'):
            pass
    assert getattr(denied.value, 'code', None) == 1008
    with factory() as db:
        assert db.query(TerminalSession).one().pid == original['pid']


def status_of(ws):
    for _ in range(10):
        message = ws.receive()
        if message.get('text'):
            return json.loads(message['text'])
    raise AssertionError('status frame not received')


def test_second_writer_rejected_and_role_released_on_exit(api_terminal):
    """Fase 2: um writer exclusivo; liberação garantida no disconnect."""
    client, run_id, _, _ = api_terminal
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal?role=writer'):
        with pytest.raises(Exception) as denied:
            with client.websocket_connect(f'/ws/runs/{run_id}/terminal?role=writer'):
                pass
        assert getattr(denied.value, 'code', None) == 1008
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal?role=writer') as ws:
        assert status_of(ws)['role'] == 'writer'


def test_invalid_role_is_rejected(api_terminal):
    client, run_id, _, _ = api_terminal
    with pytest.raises(Exception) as denied:
        with client.websocket_connect(f'/ws/runs/{run_id}/terminal?role=bogus'):
            pass
    assert getattr(denied.value, 'code', None) == 1008


def test_client_limit_is_enforced(api_terminal, monkeypatch):
    """Fase 2: limite de clientes concorrentes por execução."""
    monkeypatch.setattr(run_terminal, 'MAX_WS_CLIENTS_PER_RUN', 2)
    client, run_id, _, _ = api_terminal
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal'):
        with client.websocket_connect(f'/ws/runs/{run_id}/terminal'):
            with pytest.raises(Exception) as denied:
                with client.websocket_connect(f'/ws/runs/{run_id}/terminal'):
                    pass
            assert getattr(denied.value, 'code', None) == 1008


def test_observer_receives_output_but_input_is_ignored(api_terminal):
    """Fase 3: observer acompanha em tempo real e não consegue escrever."""
    client, run_id, _, _ = api_terminal
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal?role=writer') as writer:
        with client.websocket_connect(f'/ws/runs/{run_id}/terminal?role=observer') as observer:
            assert status_of(writer)['role'] == 'writer'
            assert status_of(observer)['role'] == 'observer'
            forbidden = f'FORBIDDEN_{uuid4().hex[:8]}'
            send_input(observer, f'printf "{forbidden}\\n"\n')
            allowed = f'ALLOWED_{uuid4().hex[:8]}'
            send_input(writer, f'printf "{allowed}\\n"\n')
            received = read_until(observer, allowed)
            assert allowed.encode() in received
            assert forbidden.encode() not in received


def test_takeover_transfers_writing_without_dropping_observers(api_terminal):
    """Fase 3: assumir controle não afeta quem só observa."""
    client, run_id, _, _ = api_terminal
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal?role=writer'):
        with client.websocket_connect(f'/ws/runs/{run_id}/terminal?role=observer') as observer:
            with client.websocket_connect(f'/ws/runs/{run_id}/terminal?role=writer&takeover=1') as new_writer:
                assert status_of(new_writer)['role'] == 'writer'
                marker = f'TAKEOVER_{uuid4().hex[:8]}'
                send_input(new_writer, f'printf "{marker}\\n"\n')
                assert marker.encode() in read_until(observer, marker)


def test_recreate_after_close_gets_fresh_session(api_terminal):
    client, run_id, _, _ = api_terminal
    first = client.post(f'/api/runs/{run_id}/terminal').json()
    client.delete(f'/api/runs/{run_id}/terminal')
    second = client.post(f'/api/runs/{run_id}/terminal').json()
    assert second['state'] == 'RUNNING' and second['id'] != first['id']


def test_idle_reaper_closes_session_and_allows_a_new_one(api_terminal, monkeypatch):
    """Fase 4: inatividade acima do timeout encerra PTY; recriação fica liberada."""
    monkeypatch.setenv('WORKDEV_TERMINAL_IDLE_TIMEOUT_SECONDS', '0.3')
    client, run_id, _, _ = api_terminal
    first = client.post(f'/api/runs/{run_id}/terminal').json()
    deadline = time.monotonic() + 10
    state = {}
    while time.monotonic() < deadline:
        state = client.get(f'/api/runs/{run_id}/terminal').json()
        if state['state'] == 'CLOSED':
            break
        time.sleep(.1)
    assert state['state'] == 'CLOSED' and not state['pty']['available']
    second = client.post(f'/api/runs/{run_id}/terminal').json()
    assert second['state'] == 'RUNNING' and second['id'] != first['id']


def test_terminal_logs_never_contain_raw_stdin_or_stdout(api_terminal, caplog):
    """Fase 5: eventos de ciclo de vida chegam; payloads de terminal, nunca."""
    import logging
    client, run_id, _, _ = api_terminal
    marker = f'SECRET_STDIN_{uuid4().hex[:10]}'
    with caplog.at_level(logging.INFO, logger='workdev.terminal'):
        with client.websocket_connect(f'/ws/runs/{run_id}/terminal') as writer:
            send_input(writer, f'echo "{marker}"\n')
            read_until(writer, marker)
        client.delete(f'/api/runs/{run_id}/terminal')
    assert marker not in caplog.text
    assert 'writer claimed' in caplog.text
    assert 'session created' in caplog.text


def test_uuid_aliases_cannot_bypass_writer_exclusivity(api_terminal):
    """Regressão revisor: alias de UUID (case/sem hífen) não abre slot paralelo."""
    client, run_id, _, _ = api_terminal
    upper = str(run_id).upper()
    bare = str(run_id).replace('-', '')
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal?role=writer'):
        for alias in (upper, bare):
            with pytest.raises(Exception) as denied:
                with client.websocket_connect(f'/ws/runs/{alias}/terminal?role=writer'):
                    pass
            assert getattr(denied.value, 'code', None) == 1008


def test_takeover_via_uuid_alias_kicks_previous_writer(api_terminal):
    """Takeover por alias fecha o writer antigo e assume o mesmo slot canônico."""
    client, run_id, _, _ = api_terminal
    alias = str(run_id).upper()
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal?role=writer'):
        with client.websocket_connect(f'/ws/runs/{alias}/terminal?role=writer&takeover=1') as writer:
            assert status_of(writer)['role'] == 'writer'
            marker = f'ALIAS_{uuid4().hex[:8]}'
            send_input(writer, f'printf "{marker}\\n"\n')
            assert marker.encode() in read_until(writer, marker)


def test_transient_supervisor_error_never_unbinds_session(api_terminal, monkeypatch):
    """Regressão revisor: timeout temporário no health não apaga vínculo nem cria outro PTY."""
    client, run_id, factory, _ = api_terminal
    original = client.post(f'/api/runs/{run_id}/terminal').json()
    original_request = TerminalSessionManager._request
    def flaky(self, item, op, **kwargs):
        if op == 'health':
            raise OSError('temporary supervisor timeout')
        return original_request(self, item, op, **kwargs)
    monkeypatch.setattr(TerminalSessionManager, '_request', flaky)
    degraded = client.post(f'/api/runs/{run_id}/terminal').json()
    assert degraded['state'] == 'ERROR' and degraded['id'] == original['id']
    TerminalSessionManager._request = original_request  # supervisor recuperado
    with factory() as db:
        assert db.query(TerminalSession).count() == 1
    recovered = client.post(f'/api/runs/{run_id}/terminal').json()
    assert recovered['state'] == 'RUNNING' and recovered['id'] == original['id']


def test_confirmed_close_still_allows_recreation(api_terminal):
    """CLOSED confirmado pelo resultado do worker libera a criação de nova sessão."""
    client, run_id, factory, _ = api_terminal
    first = client.post(f'/api/runs/{run_id}/terminal').json()
    client.delete(f'/api/runs/{run_id}/terminal')
    with factory() as db:
        assert db.query(TerminalSession).count() == 1
    second = client.post(f'/api/runs/{run_id}/terminal').json()
    assert second['state'] == 'RUNNING' and second['id'] != first['id']


def test_cancelled_attach_closes_orphan_socket_and_releases_writer(api_terminal, monkeypatch):
    """Regressão revisor: cancelamento fecha socket tardio e libera o slot de writer."""
    import asyncio
    import threading
    client, run_id, _, _ = api_terminal
    client.post(f'/api/runs/{run_id}/terminal')
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    class Connection:
        closed = False
        def close(self):
            self.closed = True
    connection = Connection()
    original_attach = run_terminal._attach
    def attach(_run_id):
        entered.set()
        release.wait(5)
        returned.set()
        return connection, {}, b''
    monkeypatch.setattr(run_terminal, '_attach', attach)

    class FakeHeaders:
        def getlist(self, _name):
            return []

    class FakeWS:
        headers = FakeHeaders()
        query_params = {'role': 'writer'}
        cookies = {COOKIE_NAME: create_session_token()}
        async def close(self, code=1000, reason=''):
            pass
        async def accept(self):
            pass
        async def send_bytes(self, _):
            pass
        async def send_text(self, _):
            pass
        async def receive(self):
            await asyncio.sleep(3600)

    async def drive():
        task = asyncio.create_task(run_terminal.run_terminal_ws(FakeWS(), str(run_id)))
        for _ in range(200):
            if entered.is_set():
                break
            if task.done():
                await task
                pytest.fail("handler terminou antes de iniciar _attach")
            await asyncio.sleep(.01)
        else:
            pytest.fail("_attach não iniciou dentro de 2 segundos")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        while not returned.is_set():
            await asyncio.sleep(.01)
        await asyncio.sleep(.05)

    asyncio.run(drive())
    run_terminal._attach = original_attach  # tentativa seguinte usa attach real
    assert connection.closed, 'socket tardio do attach deve ser fechado explicitamente'
    assert run_terminal._clients.get(str(run_id)) in (None, {'writer': None, 'total': 0})
    # Slot livre: um writer explícito entra na tentativa seguinte.
    with client.websocket_connect(f'/ws/runs/{run_id}/terminal?role=writer') as writer:
        assert status_of(writer)['role'] == 'writer'
