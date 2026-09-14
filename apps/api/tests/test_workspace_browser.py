"""Chromium + built cockpit + HTTP/WS + real tmux/PTY; isolated persistence."""
import base64
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

import pytest
from tests.test_workspace_http import workspace_api  # noqa: F401
from app.main import app
from app.auth import COOKIE_NAME, create_session_token
from app.routers import terminal
from app.services import agent_lifecycle as lifecycle, agent_snapshot
from app.services.terminal_sessions import TerminalSessionManager

pytestmark = pytest.mark.skipif(os.getenv('PLAYWRIGHT_E2E') != '1', reason='opt-in Chromium E2E')


def test_workspace_agent_and_run_detach_reconnect_stop_and_audit(workspace_api, tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright, expect
    import uvicorn
    client, run_id, factory, Run, Event = workspace_api
    standalone='workspace-kimi-' + uuid4().hex[:10]
    run_session=f'auto-kimi-{run_id}'
    monkeypatch.setitem(terminal.ALLOWED_SESSIONS, 'kimi', standalone)
    monkeypatch.setitem(terminal.STANDBY_COMMANDS, 'kimi', [sys.executable, '-u', '-c',
        'import sys; print("AGENT_READY",flush=True); [print(line,flush=True) for line in sys.stdin]'])
    monkeypatch.setattr(lifecycle, 'active_work', lambda db, agent: None)
    monkeypatch.setattr(lifecycle, 'GRACEFUL_TIMEOUT_SECONDS', .2)
    path=tmp_path/'status.json'
    monkeypatch.setenv('AGENTS_HEALTH_STATE', str(path))
    monkeypatch.setattr(terminal, '_HEALTH_STATE_FILE', path)
    listener=socket.socket(); listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app, host='127.0.0.1',port=port,lifespan='off',log_level='critical'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True)
    with tempfile.TemporaryDirectory(prefix='wd-ws-') as root:
        monkeypatch.setenv('WORKDEV_TERMINAL_DIR',root)
        try:
            assert client.post('/api/agents/kimi/start').status_code==200
            subprocess.run(['tmux','new-session','-d','-s',run_session,'bash','--noprofile','--norc'],check=True)
            with lifecycle.run_lock(run_id), lifecycle.agent_lock('kimi'):
                row=lifecycle.bind_run('kimi',run_id,run_session)
            assert os.stat(f"/proc/{row['pid']}").st_uid==os.getuid()
            assert client.post(f'/api/runs/{run_id}/terminal').status_code==200
            state=lifecycle.read_state('kimi',standalone)
            agent_snapshot.publish([agent_snapshot.from_physical('kimi',state)])
            thread.start()
            deadline=time.monotonic()+8
            while not server.started and time.monotonic()<deadline: time.sleep(.02)
            assert server.started
            origin=f'http://127.0.0.1:{port}'
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
                context=browser.new_context()
                context.add_cookies([{'name':COOKIE_NAME,'value':create_session_token(),'url':origin}])
                context.route('**/api/settings',lambda route: route.fulfill(status=503,body='{}'))
                page=context.new_page(); page.goto(origin+'/agents')
                page.get_by_role('tab',name='Kimi Code').click()
                expect(page.get_by_role('link',name='Workspace E2E',exact=False)).to_be_visible()
                expect(page.locator('.xterm-helper-textarea')).to_be_attached()
                page.get_by_role('button',name='Fechar terminal do agente').click()
                assert lifecycle.session_exists(standalone)
                page.get_by_role('button',name='Abrir terminal do agente').click()
                expect(page.locator('.xterm-helper-textarea')).to_be_attached()
                page.screenshot(path='/tmp/workdev-workspace-real.png',full_page=True)
                page.get_by_role('link',name='Workspace E2E',exact=False).click()
                expect(page.get_by_text('Conectado',exact=True)).to_be_visible(timeout=15000)
                marker='WORKSPACE_'+uuid4().hex[:8]
                page.locator('.xterm-helper-textarea').focus()
                page.keyboard.type(f'echo {marker}'); page.keyboard.press('Enter')
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    before=client.get(f'/api/runs/{run_id}/terminal').json()
                    if marker.encode() in base64.b64decode(before['buffer']['data']): break
                    time.sleep(.05)
                assert marker.encode() in base64.b64decode(before['buffer']['data'])
                page.close()
                assert lifecycle.session_exists(run_session)
                page=context.new_page(); page.goto(origin+f'/runs/{run_id}/terminal')
                expect(page.get_by_text('Conectado',exact=True)).to_be_visible(timeout=15000)
                after=client.get(f'/api/runs/{run_id}/terminal').json()
                assert before['pid']==after['pid'] and before['id']==after['id']
                page.goto(origin+'/agents'); page.get_by_role('tab',name='Kimi Code').click()
                page.on('dialog',lambda dialog: dialog.accept())
                page.get_by_role('button',name='Parar Run',exact=True).click()
                expect(page.get_by_role('link',name='Workspace E2E',exact=False)).not_to_be_visible(timeout=15000)
                assert not lifecycle.session_exists(run_session)
                assert lifecycle.session_exists(standalone)
                assert client.post('/api/agents/kimi/stop?confirm=true').status_code==200
                assert not lifecycle.session_exists(standalone)
                with factory() as db:
                    assert db.get(Run,run_id).status=='cancelled'
                    events=db.query(Event).all()
                    actions={e.event_type for e in events if e.payload.get('result')=='succeeded'}
                    assert {'workspace.start_agent','workspace.stop_agent','workspace.stop_run','workspace.reconnect'} <= actions
                browser.close()
        finally:
            server.should_exit=True
            if thread.ident: thread.join(timeout=10)
            listener.close()
            with factory() as db:
                try: TerminalSessionManager(db,root).close(run_id)
                except Exception: pass
            for session in (standalone,run_session):
                subprocess.run(['tmux','kill-session','-t','='+session],capture_output=True)
