"""Regressions from independent review fe9e5e0e: real lifecycle, fake processes."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import pytest
from app.services import agent_lifecycle as lifecycle, agent_snapshot as snapshot
from app.routers import terminal

SPEC = importlib.util.spec_from_file_location('review_health', Path(__file__).parents[3] / 'scripts/agents_healthcheck.py')
health = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = health
SPEC.loader.exec_module(health)


@pytest.fixture
def fake_processes(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle, 'GROUPS_FILE', tmp_path / 'groups.json')
    monkeypatch.setenv('AGENTS_HEALTH_STATE', str(tmp_path / 'status.json'))
    state = {'alive': False, 'starts': 0}
    def read(agent, session, **kw):
        return lifecycle.AgentState(agent=agent, session=session,
            session_exists=state['alive'], current_process='codex' if state['alive'] else '')
    def command(args, timeout=10):
        if 'new-session' in args:
            state['alive'] = True
            state['starts'] += 1
        if 'kill-session' in args:
            state['alive'] = False
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(lifecycle, 'read_state', read)
    monkeypatch.setattr(lifecycle, '_run', command)
    monkeypatch.setattr(lifecycle, 'active_work', lambda *args: None)
    monkeypatch.setattr(health, 'capture_recent', lambda *args: '')
    monkeypatch.setattr(terminal, '_current_process', lambda *_args: 'codex' if state['alive'] else '')
    return state


def test_always_on_recovers_after_each_crash_but_respects_disconnect(fake_processes):
    for count in (1, 2, 3):
        fake_processes['alive'] = False
        row = health.collect_agent('codex', 'codex', None, allow_restart=True)
        assert row.runtime_state.value == 'ONLINE'
        assert fake_processes['starts'] == count
        assert lifecycle.read_operation('codex')['desired'] == 'ONLINE'
    lifecycle.stop('codex', 'codex')
    row = health.collect_agent('codex', 'codex', None, allow_restart=True)
    assert row.runtime_state.value == 'OFFLINE'
    assert fake_processes['starts'] == 3


def test_finalize_auto_keeps_explicit_disconnect_and_legacy_connect_updates_intent(fake_processes, monkeypatch):
    lifecycle.stop('codex', 'codex')
    monkeypatch.setattr(terminal, '_stop_standby_session', lambda *_args: True)
    finalized = terminal.finalize_auto_runtime('codex', 'run-test')
    assert not finalized['standby_started']
    assert fake_processes['starts'] == 0
    assert health.collect_agent('codex', 'codex', None).runtime_state.value == 'OFFLINE'
    connected = asyncio.run(terminal.start_agent_session('codex'))
    assert connected['running']
    assert lifecycle.read_operation('codex')['desired'] == 'ONLINE'
    assert health.collect_agent('codex', 'codex', None).runtime_state.value == 'ONLINE'
    disconnected = asyncio.run(terminal.stop_agent_session('codex', confirm=True))
    assert not disconnected['running']
    assert lifecycle.read_operation('codex')['desired'] == 'OFFLINE'


def test_collector_never_waits_behind_lifecycle_lock(fake_processes):
    started = time.monotonic()
    with lifecycle.agent_lock('codex'):
        assert lifecycle.try_recover('codex', 'codex', ['unused']) is None
    assert time.monotonic() - started < .5
    assert fake_processes['starts'] == 0


@pytest.mark.parametrize('prompt', ['permission required', 'requires your approval',
    'deseja continuar', 'aprovar?', 'confirmar?', '❯ 1. yes', 'press enter to continue',
    'waiting for input', 'do you approve', '[y/n]'])
def test_waiting_input_recognizes_legacy_approval_prompts(prompt):
    output = prompt + '\n' + '\n'.join(['option'] * 10)
    row = health.classify('codex', 'codex', 'codex', output, snapshot.now())
    assert row.status == 'waiting_input'
    resumed = health.classify('codex', 'codex', 'codex', output + '\nexecuting command', snapshot.now())
    assert resumed.status != 'waiting_input'


@pytest.mark.parametrize('runtime,expected', [('OFFLINE', 1), ('ERROR', 1), ('ONLINE', 0)])
def test_exit_code_marks_unhealthy_always_on(runtime, expected):
    row = snapshot.AgentSnapshot(agent='codex', runtime_state=runtime, activity_state='IDLE', checked_at=snapshot.now())
    assert health.health_exit_code([row]) == expected
    row.agent = 'kimi'
    assert health.health_exit_code([row]) == 0


def test_persistence_matches_runtime_policy():
    for agent in ('codex', 'claude'):
        assert snapshot.is_persistent(agent, agent)
        assert not snapshot.is_persistent(agent, f'auto-{agent}-run')
    for agent in ('kimi', 'qwen', 'gemini', 'local-code'):
        assert not snapshot.is_persistent(agent, agent)


def test_unconfigured_gpu_remains_distinguishable(monkeypatch):
    from app.routers.agent_runtimes import list_agent_runtimes
    for name in ('WORKDEV_OLLAMA_HOSTINGER_URL', 'WORKDEV_OLLAMA_HOSTINGER_MODEL'):
        monkeypatch.delenv(name, raising=False)
    rows = list_agent_runtimes()['runtimes']
    gpu = next(row for row in rows if row['id'] == 'gpu-hostinger')
    assert gpu['status'] == 'unconfigured'
    assert gpu['status_label'] == 'Não configurado'
    assert not gpu['dispatchable']
