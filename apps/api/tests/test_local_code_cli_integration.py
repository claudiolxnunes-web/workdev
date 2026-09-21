"""Real Qwen TUI + real tmux, private socket/home, local fake inference only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import threading
import time
from uuid import uuid4

import pytest

from app.services import agent_lifecycle as lifecycle, local_code_channel as channel

pytestmark = pytest.mark.skipif(os.getenv('LOCAL_CODE_CLI_E2E') != '1', reason='opt-in real Qwen TUI')


def eventually(check, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.1)
    raise AssertionError('Condition not reached')


@pytest.fixture
def real_qwen(tmp_path, monkeypatch):
    assert shutil.which('qwen') and shutil.which('tmux')
    requests = []
    hold = threading.Event()
    hold.set()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            body = json.dumps({'object': 'list', 'data': [{'id': 'workdev-qwen27b', 'object': 'model'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(payload)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            hold.wait(timeout=60)
            try:
                for delta, reason in [({'role': 'assistant', 'content': 'WORKDEV_E2E_RECEIVED'}, None), ({}, 'stop')]:
                    chunk = {'id': 'test-completion', 'object': 'chat.completion.chunk',
                             'created': 1, 'model': 'workdev-qwen27b',
                             'choices': [{'index': 0, 'delta': delta, 'finish_reason': reason}]}
                    self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
                    self.wfile.flush()
                self.wfile.write(b'data: [DONE]\n\n')
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    socket = f'local-code-test-{uuid4().hex[:10]}'
    original = lifecycle._run

    def command(argv, timeout=10):
        if argv[0] == 'tmux':
            argv = ['tmux', '-L', socket, *argv[1:]]
        return original(argv, timeout)

    monkeypatch.setattr(lifecycle, '_run', command)
    monkeypatch.setattr(lifecycle, 'GROUPS_FILE', tmp_path / 'groups.json')
    home = tmp_path / 'home'
    home.mkdir()
    cwd = tmp_path / 'project'
    cwd.mkdir()
    settings = tmp_path / 'models.json'
    settings.write_text(json.dumps({
        'modelProviders': {'openai': [{'id': 'workdev-qwen27b',
            'name': 'Test', 'baseUrl': f'http://127.0.0.1:{server.server_port}/v1',
            'envKey': 'WORKDEV_LOCAL_CODE_KEY'}]},
        'model': {'name': 'workdev-qwen27b'},
        'security': {'auth': {'selectedType': 'openai'}, 'folderTrust': {'enabled': False}},
        'telemetry': {'enabled': False},
    }))
    launch = ['env', '-i', 'PATH=/usr/bin:/bin', f'HOME={home}', 'TERM=xterm-256color',
              f'WORKDEV_AGENT_CWD={cwd}', f'WORKDEV_AGENT_GROUPS_FILE={tmp_path / "groups.json"}',
              f'LOCAL_SETTINGS_FILE={settings}', 'PYTHONDONTWRITEBYTECODE=1',
              '/opt/workdev/scripts/start_local_agent.sh']
    try:
        result = command(['tmux', 'new-session', '-d', '-s', 'local-code', '-x', '150', '-y', '40', 'env -i TMUX="$TMUX" ' + shlex.join(launch[2:])])
        assert result.returncode == 0, result.stderr
        try:
            eventually(lambda: channel.read().get('phase') == 'idle', timeout=15)
        except AssertionError:
            capture = command(['tmux', 'capture-pane', '-p', '-t', '=local-code:', '-S', '-100'])
            pytest.fail('Qwen startup failed: ' + capture.stdout + capture.stderr)
        yield requests, hold, command
    finally:
        hold.set()
        command(['tmux', 'kill-server'])  # This socket is exclusive to this fixture.
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_plan_reaches_real_qwen_and_second_run_waits(real_qwen):
    requests, _, command = real_qwen
    pid = lifecycle.pane_pid('local-code')
    run_id = uuid4()
    plan = f'Plano de teste {run_id}. Responda WORKDEV_E2E_RECEIVED; não execute ferramentas.'
    with lifecycle.agent_lock('local-code'):
        data = channel.reserve(run_id, uuid4(), plan)
        assert data is not None
        channel.send_marker(data)
        channel.wait_ack(run_id)
    eventually(lambda: channel.read().get('phase') == 'turn_done')
    assert plan in json.dumps(requests, ensure_ascii=False)
    assert channel.reserve(uuid4(), uuid4(), 'segunda run') is None
    capture = command(['tmux', 'capture-pane', '-p', '-t', '=local-code:', '-S', '-150'])
    assert 'WORKDEV_E2E_RECEIVED' in capture.stdout
    with lifecycle.run_lock(run_id):
        assert lifecycle.stop_run_process('local-code', run_id)['stopped']
    assert lifecycle.pane_pid('local-code') == pid
    assert channel.release(run_id)


def test_cancel_stream_preserves_real_qwen(real_qwen):
    requests, hold, _ = real_qwen
    hold.clear()
    pid = lifecycle.pane_pid('local-code')
    run_id = uuid4()
    with lifecycle.agent_lock('local-code'):
        data = channel.reserve(run_id, uuid4(), 'Responda somente o marcador de teste; sem ferramentas.')
        channel.send_marker(data)
        channel.wait_ack(run_id)
    eventually(lambda: bool(requests))
    with lifecycle.run_lock(run_id):
        assert lifecycle.stop_run_process('local-code', run_id)['stopped']
    assert lifecycle.pane_pid('local-code') == pid
    assert lifecycle.session_exists('local-code')


from tests.test_local_code_build import queue_db  # noqa: F401, E402


def test_worker_to_real_cli_persists_receipt(real_qwen, queue_db):
    from app.services import local_code_build as build
    requests, _, _ = real_qwen
    run_id, job_id = queue_db.new()
    with queue_db.factory() as db:
        build.dispatch(db, db.get(queue_db.Job, job_id), db.get(queue_db.Run, run_id))
    eventually(lambda: channel.read().get('phase') == 'turn_done')
    with queue_db.factory() as db:
        receipt = db.query(queue_db.Event).filter_by(run_id=run_id, event_type='build.cli_received').one()
        assert receipt.payload['pid'] == lifecycle.pane_pid('local-code')
        assert receipt.payload['tmux_session'] == 'local-code'
        assert str(run_id) in json.dumps(requests)
        run = db.get(queue_db.Run, run_id)
        run.status = 'review'
        db.commit()
        build.reconcile(db)
        assert db.get(queue_db.Job, job_id).state == 'done'
        assert channel.read()['phase'] == 'idle'


@pytest.mark.skipif(os.getenv('PLAYWRIGHT_E2E') != '1', reason='opt-in Chromium')
def test_browser_refresh_and_disconnect_preserve_real_qwen(real_qwen, queue_db, monkeypatch):
    import socket
    import uvicorn
    from unittest.mock import AsyncMock
    from playwright.sync_api import sync_playwright, expect
    from app.main import app
    from app.auth import COOKIE_NAME, create_session_token
    from app.routers import terminal
    from app.services import local_code_build as build

    requests, hold, command = real_qwen
    hold.clear()
    run_id, job_id = queue_db.new()
    with queue_db.factory() as db:
        build.dispatch(db, db.get(queue_db.Job, job_id), db.get(queue_db.Run, run_id))
    eventually(lambda: bool(requests))
    pid = lifecycle.pane_pid('local-code')
    socket_path = command(['tmux', 'display-message', '-p', '-t', '=local-code:', '#{socket_path}']).stdout.strip()
    original_popen = subprocess.Popen
    def private_popen(argv, *args, **kwargs):
        if isinstance(argv, list) and argv[0] == 'tmux' and '-L' not in argv and '-S' not in argv:
            argv = ['tmux', '-S', socket_path, *argv[1:]]
        return original_popen(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', private_popen)
    monkeypatch.setattr(terminal, '_agent_status', AsyncMock(return_value={
        'agent': 'local-code', 'runtime_state': 'ONLINE', 'activity_state': 'BUSY',
        'running': True, 'active_run_id': str(run_id), 'persistent': True,
    }))
    monkeypatch.setenv('WORKDEV_SESSION_SECRET', 'isolated-browser-test')
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan='off', log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    eventually(lambda: server.started, timeout=10)
    origin = f'http://127.0.0.1:{port}'
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context()
            context.add_cookies([{'name': COOKIE_NAME, 'value': create_session_token(), 'url': origin}])
            context.route('**/api/settings', lambda route: route.fulfill(status=503, body='{}'))
            page = context.new_page()
            url = origin + '/agents/local-code/terminal'
            page.goto(url)
            expect(page.get_by_text('Conectado', exact=True)).to_be_visible(timeout=15000)
            page.reload()
            expect(page.get_by_text('Conectado', exact=True)).to_be_visible(timeout=15000)
            page.close()
            eventually(lambda: not terminal._active_connections)
            assert lifecycle.pane_pid('local-code') == pid
            assert channel.read()['run_id'] == str(run_id)
            page = context.new_page()
            page.goto(url)
            expect(page.get_by_text('Conectado', exact=True)).to_be_visible(timeout=15000)
            assert lifecycle.pane_pid('local-code') == pid
            with queue_db.factory() as db:
                assert db.get(queue_db.Run, run_id).status == 'running'
                assert db.query(queue_db.Event).filter_by(run_id=run_id, event_type='build.cli_received').count() == 1
            sessions = command(['tmux', 'list-sessions', '-F', '#{session_name}']).stdout.splitlines()
            assert sessions == ['local-code']
            browser.close()
    finally:
        hold.set()
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
    assert not thread.is_alive()
