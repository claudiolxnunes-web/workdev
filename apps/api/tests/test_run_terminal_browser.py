"""Opt-in browser E2E against built React + real WS + real PTY, isolated SQLite.

PLAYWRIGHT_E2E=1 and a Chromium installation are required. No production server.
"""
import base64
import os
import socket
import threading
import time
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(os.getenv('PLAYWRIGHT_E2E') != '1', reason='opt-in Chromium E2E')
from tests.test_run_terminal import api_terminal  # noqa: F401
from app.auth import COOKIE_NAME, create_session_token
from app.main import app


def test_browser_close_refresh_and_chat_outage_keep_same_run(api_terminal):
    from playwright.sync_api import sync_playwright, expect
    import uvicorn
    client, run_id, factory, _ = api_terminal
    created = client.post(f'/api/runs/{run_id}/terminal').json()
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, lifespan='off', log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(.02)
    assert server.started
    origin = f'http://127.0.0.1:{port}'
    marker = 'BROWSER_' + uuid4().hex[:10]
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
            context = browser.new_context()
            context.add_cookies([{'name': COOKIE_NAME, 'value': create_session_token(), 'url': origin}])
            # Chat is unavailable throughout; terminal must not request it.
            chat_requests = []
            def unavailable(route):
                chat_requests.append(route.request.url)
                route.fulfill(status=503, body='Chat unavailable')
            context.route('**/api/chat/**', unavailable)
            context.route('**/api/ai/**', unavailable)
            context.route('**/api/settings', lambda route: route.fulfill(status=503, body='{}'))
            url = f'{origin}/runs/{run_id}/terminal'
            page = context.new_page()
            page.goto(url)
            expect(page.get_by_text('Conectado', exact=True)).to_be_visible(timeout=15000)
            page.locator('.xterm-helper-textarea').focus()
            page.keyboard.type(f'export WD_RECONNECT_TOKEN={marker}; printf "$WD_RECONNECT_TOKEN\\n"')
            page.keyboard.press('Enter')
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                before = client.get(f'/api/runs/{run_id}/terminal').json()
                if marker.encode() in base64.b64decode(before['buffer']['data']):
                    break
                time.sleep(.05)
            assert marker.encode() in base64.b64decode(before['buffer']['data'])
            page.close()
            page = context.new_page()
            page.goto(url)
            expect(page.get_by_text('Conectado', exact=True)).to_be_visible(timeout=15000)
            assert page.locator('[data-run-id]').get_attribute('data-run-id') == str(run_id)
            for refresh in (False, True):
                if refresh:
                    page.reload()
                    expect(page.get_by_text('Conectado', exact=True)).to_be_visible(timeout=15000)
                state = client.get(f'/api/runs/{run_id}/terminal').json()
                assert state['id'] == created['id'] and state['pid'] == created['pid']
                assert marker.encode() in base64.b64decode(state['buffer']['data'])
            page.locator('.xterm-helper-textarea').focus()
            page.keyboard.type('printf "RECOVERED_%s\\n" "$WD_RECONNECT_TOKEN"')
            page.keyboard.press('Enter')
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                state = client.get(f'/api/runs/{run_id}/terminal').json()
                if f'RECOVERED_{marker}'.encode() in base64.b64decode(state['buffer']['data']):
                    break
                time.sleep(.05)
            assert f'RECOVERED_{marker}'.encode() in base64.b64decode(state['buffer']['data'])
            assert not chat_requests
            page.screenshot(path='/tmp/workdev-reconnect-e2e.png')
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
    assert not thread.is_alive()
