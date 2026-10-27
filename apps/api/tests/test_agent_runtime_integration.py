"""Physical tests use a private tmux socket and only disposable Python agents."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest
from app.services import agent_lifecycle as lifecycle, agent_snapshot as snapshots

SPEC = importlib.util.spec_from_file_location('runtime_health_integration', Path(__file__).parents[3] / 'scripts/agents_healthcheck.py')
health = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = health
SPEC.loader.exec_module(health)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    socket = str(tmp_path / 'tmux.sock')
    monkeypatch.setenv('AGENTS_HEALTH_STATE', str(tmp_path / 'status.json'))
    monkeypatch.setattr(lifecycle, 'GROUPS_FILE', tmp_path / 'groups.json')
    original = lifecycle._run
    def scoped(args, timeout=10):
        if args[0] == 'tmux':
            args = ['tmux', '-S', socket, *args[1:]]
        return original(args, timeout)
    monkeypatch.setattr(lifecycle, '_run', scoped)
    monkeypatch.setattr(health, 'run', scoped)
    monkeypatch.setattr(lifecycle, 'active_work', lambda *_args: None)
    yield scoped
    subprocess.run(['tmux', '-S', socket, 'kill-server'], capture_output=True, timeout=5)


def start_fixture():
    return lifecycle.start('codex', 'fixture', [sys.executable, '-c', 'import time; time.sleep(300)'])


def poll():
    row = health.collect_agent('codex', 'fixture', None)
    snapshots.publish([row])
    return row


def test_forced_agent_death_reaches_offline_or_error(runtime, audit_store):
    start_fixture()
    deadline = time.monotonic()+5
    while poll().runtime_state.value != 'ONLINE' and time.monotonic() < deadline:
        time.sleep(.05)
    assert poll().runtime_state.value == 'ONLINE'
    pid = lifecycle.pane_pid('fixture')
    assert pid and pid != os.getpid()
    started = time.monotonic()
    os.kill(pid, signal.SIGKILL)
    before = len(audit_store.events())
    while time.monotonic()-started < 15:
        poll()
        confirmed = snapshots.read_snapshot(['codex'])['agents'][0]['runtime_state']
        if confirmed in {'OFFLINE', 'ERROR'}:
            break
        assert len(audit_store.events()) == before
        time.sleep(.1)
    assert confirmed in {'OFFLINE', 'ERROR'}
    assert 10 <= time.monotonic()-started < 15
    assert len(audit_store.events()) == before + 1


def test_stopping_survives_reader_restart_and_stop_is_idempotent(runtime, monkeypatch):
    start_fixture()
    pid = lifecycle.pane_pid('fixture')
    time.sleep(.1)
    assert start_fixture()['already_running']
    assert lifecycle.pane_pid('fixture') == pid
    entered, release = threading.Event(), threading.Event()
    def delayed(args, timeout=10):
        if args[:2] == ['tmux', 'kill-session']:
            entered.set()
            assert release.wait(10)
        return runtime(args, timeout)
    monkeypatch.setattr(lifecycle, '_run', delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        stop = pool.submit(lifecycle.stop, 'codex', 'fixture')
        try:
            assert entered.wait(5)
            assert snapshots.read_snapshot(['codex'])['agents'][0]['runtime_state'] == 'STOPPING'
            code = '''import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers.terminal import router
app=FastAPI(); app.include_router(router)
with TestClient(app) as c:
 print(json.dumps(c.get('/api/agents/status').json(), sort_keys=True))
'''
            responses = [subprocess.check_output([sys.executable, '-c', code], cwd=str(Path(__file__).parents[1]), text=True, timeout=5) for _ in range(2)]
            assert json.loads(responses[0]) == json.loads(responses[1])
            assert 'STOPPING' in responses[0]
        finally:
            release.set()
        assert stop.result(timeout=15)['stopped']
    assert lifecycle.stop('codex', 'fixture')['already_offline']
    assert poll().runtime_state.value == 'OFFLINE'


def test_process_lock_serializes_separate_workers(tmp_path):
    target = tmp_path / 'counter'
    target.write_text('0')
    code = '''import sys, time
from pathlib import Path
from app.services.agent_snapshot import file_lock
p=Path(sys.argv[1])
with file_lock(p.with_suffix('.lock')):
 n=int(p.read_text()); time.sleep(.03); p.write_text(str(n+1))
'''
    processes = [subprocess.Popen([sys.executable, '-c', code, str(target)], cwd=str(Path(__file__).parents[1])) for _ in range(8)]
    results = [process.wait(timeout=10) for process in processes]
    assert results == [0] * 8
    assert target.read_text() == '8'


from tests.test_runtime_state_audit import audit_store  # noqa: F401 -- isolated audit database fixture


def test_real_tmux_lifecycle_is_audited_and_http_polling_is_read_only(runtime, audit_store):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routers.terminal import router
    start_fixture()
    time.sleep(.1)
    poll()
    app=FastAPI()
    app.include_router(router)
    before=audit_store.events()
    with TestClient(app) as client:
        for _ in range(3):
            response=client.get('/api/agents/status')
            assert response.status_code==200
    assert audit_store.events()==before
    assert lifecycle.stop('codex','fixture')['stopped']
    events=audit_store.events()
    assert [event['novo_estado']['runtime'] for event in events][-2:]==['STOPPING','OFFLINE']
    for left,right in zip(events,events[1:]):
        assert left['novo_estado']==right['estado_anterior']
        assert left['timestamp']<right['timestamp']
