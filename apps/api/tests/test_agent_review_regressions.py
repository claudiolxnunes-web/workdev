"""Regressions from independent review fe9e5e0e: real lifecycle, fake processes."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

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


def test_old_operation_error_reconciles_to_physical_state(fake_processes):
    fake_processes['alive'] = True
    operation = {'phase': 'ERROR', 'desired': 'OFFLINE', 'running': False,
        'reason': 'identity_not_durable', 'updated_at': snapshot.now()}
    snapshot.atomic_json(lifecycle.operation_file('codex'), operation)
    assert health.collect_agent('codex', 'codex', None).runtime_state.value == 'ERROR'
    operation['updated_at'] = (datetime.now(timezone.utc) - timedelta(seconds=61)).isoformat()
    snapshot.atomic_json(lifecycle.operation_file('codex'), operation)
    assert health.collect_agent('codex', 'codex', None).runtime_state.value == 'ONLINE'
    fake_processes['alive'] = False
    assert health.collect_agent('codex', 'codex', None).runtime_state.value == 'OFFLINE'


def test_manual_start_after_completed_disconnect_is_online(fake_processes):
    lifecycle.stop('qwen', 'qwen')
    fake_processes['alive'] = True
    row = health.collect_agent('qwen', 'qwen', None)
    assert row.runtime_state.value == 'ONLINE'
    assert row.reason is None


def test_failed_operation_is_finished_and_timestamped(fake_processes):
    with pytest.raises(RuntimeError):
        with lifecycle.lifecycle_operation('codex', 'codex', 'STOPPING'):
            raise RuntimeError('failure')
    operation = lifecycle.read_operation('codex')
    assert operation['phase'] == 'ERROR'
    assert not operation['running']
    assert not lifecycle.operation_active(operation)
    assert (datetime.now(timezone.utc) - datetime.fromisoformat(operation['updated_at'])).total_seconds() < 2


@pytest.mark.parametrize('status,badge', [('blocked', 'blocked'), ('review', 'awaiting_user'),
    ('completed', 'completed'), ('running', 'executing')])
def test_run_badges_survive_snapshot_and_concurrent_api_reads(fake_processes, status, badge):
    fake_processes['alive'] = True
    work = {'run_id': 'r', 'status': 'running'} if status == 'running' else None
    row = health.collect_agent('codex', 'codex', None, work=work, run_status=status)
    snapshot.publish([row])
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: snapshot.read_snapshot(['codex'])['agents'][0], range(8)))
    assert all(row == rows[0] for row in rows)
    assert rows[0]['operational_status'] == badge
    assert rows[0]['runtime_state'] == 'ONLINE'
    if status in {'blocked', 'review', 'completed'}:
        assert rows[0]['activity_state'] == 'IDLE'


@pytest.mark.parametrize('text', ['diff line 429', 'implement billing endpoint',
    '+ Error 401 Missing Authentication header', '429 account suspended due to insufficient balance'])
def test_terminal_text_does_not_override_physical_availability(fake_processes, monkeypatch, text):
    fake_processes['alive'] = True
    monkeypatch.setattr(health, 'capture_recent', lambda *_: text)
    row = health.collect_agent('codex', 'codex', None)
    assert row.runtime_state.value == 'ONLINE'


def test_slow_probe_does_not_delay_healthy_publication_and_has_budget(monkeypatch):
    monkeypatch.setattr(health, 'AGENTS', {'codex': ('codex', []), 'qwen': ('qwen', [])})
    monkeypatch.setattr(health.agent_runtimes, 'RUNTIMES', [])
    published = []
    def collect(agent, *_):
        if agent == 'qwen':
            time.sleep(.15)
        return snapshot.AgentSnapshot(agent=agent, runtime_state='ONLINE', activity_state='IDLE', checked_at=snapshot.now())
    monkeypatch.setattr(health, 'collect_agent', collect)
    start = time.monotonic()
    rows = health.collect_snapshot(None, publish_rows=lambda rows: published.extend(rows), budget=.03)
    assert time.monotonic() - start < .12
    assert published[0].agent == 'codex'
    assert next(row for row in rows if row.agent == 'qwen').reason == 'collection_timeout'
    time.sleep(.16)
    assert len(published) == 2  # No late publication from timed-out worker.


def test_notifications_debounce_and_cooldown_survive_new_collection(tmp_path, monkeypatch):
    monkeypatch.setattr(health, 'STATE_FILE', tmp_path / 'status.json')
    class Clock:
        stamp = 1000
        @classmethod
        def now(cls, _tz):
            return datetime.fromtimestamp(cls.stamp, timezone.utc)
    monkeypatch.setattr(health, 'datetime', Clock)
    messages = []
    monkeypatch.setattr(health, 'send_alert', messages.append)
    row = snapshot.AgentSnapshot(agent='codex', runtime_state='ERROR', activity_state='IDLE', checked_at=snapshot.now())
    health.notify_transitions({}, [row])
    for second in range(5, 301, 5):
        Clock.stamp = 1000 + second
        row.runtime_state = snapshot.RuntimeState.ERROR if second % 10 else snapshot.RuntimeState.OFFLINE
        health.notify_transitions({}, [row])
    assert len(messages) == 1
    row.runtime_state = snapshot.RuntimeState.ONLINE
    health.notify_transitions({}, [row])
    Clock.stamp = 1315
    health.notify_transitions({}, [row])
    assert len(messages) == 2


def test_finalize_auto_detects_cli_that_died_during_restoration(monkeypatch):
    monkeypatch.setattr(terminal, '_stop_standby_session', lambda *_: True)
    monkeypatch.setattr(lifecycle, 'try_recover', lambda *_: {'started': True})
    monkeypatch.setattr(terminal, '_current_process', lambda *_: 'bash')
    with pytest.raises(RuntimeError, match='não retornou ao standby'):
        terminal.finalize_auto_runtime('qwen', 'run-test')


def test_collection_batches_run_context_and_keeps_dispatch_jobs():
    from unittest.mock import MagicMock
    db = MagicMock()
    latest, running, jobs = MagicMock(), MagicMock(), MagicMock()
    db.query.side_effect = [latest, running, jobs]
    latest.distinct.return_value.order_by.return_value.all.return_value = [
        SimpleNamespace(agent='qwen', status='blocked')]
    running.filter.return_value.all.return_value = [SimpleNamespace(agent='codex', id='run1', status='running')]
    jobs.join.return_value.filter.return_value.all.return_value = [
        (SimpleNamespace(run_id='run2', id='job', state='running'), 'qwen')]
    statuses, work = health.load_run_context(db)
    assert db.query.call_count == 3
    assert statuses['qwen'] == 'blocked'
    assert work['qwen']['reason'] == 'dispatch_active'
    assert work['codex']['reason'] == 'run_running'


def test_refresh_contract_explicitly_reads_snapshot_only(monkeypatch):
    from app.routers.agent_runtimes import list_agent_runtimes
    monkeypatch.setattr(snapshot, 'read_snapshot', lambda ids: {'updated_at': 'sample', 'agents': [
        snapshot.public_row(snapshot.AgentSnapshot(agent=agent, runtime_state='OFFLINE',
            activity_state='IDLE', checked_at='sample')) for agent in ids]})
    response = list_agent_runtimes(refresh=True)
    assert response['source'] == 'status.json'
    assert response['probe_requested'] is False
    assert response['updated_at'] == 'sample'
