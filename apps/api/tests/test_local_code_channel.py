"""Persistent CLI identity, admission, durable delivery and cancellation."""
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.services import agent_lifecycle as lifecycle, local_code_channel as channel


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle, 'GROUPS_FILE', tmp_path / 'groups.json')
    monkeypatch.setattr(lifecycle, 'pane_pid', lambda session: 42)
    monkeypatch.setattr(lifecycle, 'process_starttime', lambda pid: 'stamp')
    monkeypatch.setattr(lifecycle, 'session_exists', lambda session: True)
    monkeypatch.setattr(channel, '_hook_identity', lambda: {'pid': 42, 'starttime': 'stamp'})
    input_file = tmp_path / 'input.jsonl'
    input_file.touch(mode=0o600)
    monkeypatch.setenv('WORKDEV_LOCAL_CODE_INPUT_FILE', str(input_file))
    channel.hook({'hook_event_name': 'SessionStart', 'session_id': 'qwen-session'})
    return input_file


def event(name, **kw):
    return channel.hook({'hook_event_name': name, 'session_id': 'qwen-session', **kw})


def finish():
    event('Stop')
    data = channel.read()
    event('UserPromptSubmit', prompt=f"{channel.IDLE_MARKER} qwen-session {data['turn_nonce']}")


def reserve(prompt='Plano aprovado de teste'):
    with lifecycle.agent_lock('local-code'):
        return channel.reserve(uuid4(), uuid4(), prompt)


def marker(data, cancel=False):
    return f"{channel.CANCEL_MARKER if cancel else channel.MARKER} {data['run_id']} {data['nonce']}"


def test_two_runs_compete_for_one_persistent_cli(cli):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert sum(row is not None for row in results) == 1
    data = next(row for row in results if row)
    binding = lifecycle.run_binding('local-code', data['run_id'])
    assert binding['session'] == 'local-code'
    assert binding['mode'] == 'persistent_cli'


def test_native_delivery_receipt_and_duplicate_rejection(cli, monkeypatch):
    data = reserve()
    tmux = Mock()
    monkeypatch.setattr(lifecycle, '_run', tmux)
    channel.send_marker(data)
    tmux.assert_not_called()
    record = json.loads(cli.read_text())
    assert record == {'type': 'submit', 'text': marker(data)}
    result = event('UserPromptSubmit', prompt=record['text'])
    assert result['hookSpecificOutput']['additionalContext'] == 'Plano aprovado de teste'
    assert channel.wait_ack(data['run_id'], timeout=.1)['acknowledged']
    assert event('UserPromptSubmit', prompt=record['text'])['decision'] == 'block'
    assert reserve() is None


def test_manual_work_blocks_queue(cli):
    event('UserPromptSubmit', prompt='Trabalho manual')
    assert reserve() is None
    finish()
    assert reserve() is not None


def test_changed_prompt_is_not_delivered(cli):
    data = reserve()
    (channel.root() / f"{data['run_id']}.txt").write_text('Contexto adulterado')
    assert event('UserPromptSubmit', prompt=marker(data))['decision'] == 'block'
    assert not channel.read()['acknowledged']


def test_restart_cannot_adopt_or_replay_active_run(cli):
    data = reserve()
    channel.hook({'hook_event_name': 'SessionStart', 'session_id': 'replacement'})
    assert channel.read()['phase'] == 'uncertain'
    assert channel.read()['run_id'] == data['run_id']
    assert reserve() is None


def test_pid_replacement_refuses_delivery(cli, monkeypatch):
    data = reserve()
    monkeypatch.setattr(lifecycle, 'process_starttime', lambda pid: 'replacement')
    with pytest.raises(lifecycle.LifecycleError, match='substituído'):
        channel.send_marker(data)
    assert cli.read_text() == ''


def test_timeout_retains_reservation(cli):
    data = reserve()
    with pytest.raises(lifecycle.LifecycleError) as error:
        channel.wait_ack(data['run_id'], timeout=0)
    assert error.value.code == 'cli_ack_timeout'
    assert reserve() is None


def test_cancel_idle_turn_preserves_tmux_and_model(cli, monkeypatch):
    data = reserve()
    event('UserPromptSubmit', prompt=marker(data))
    finish()
    run = Mock()
    monkeypatch.setattr(lifecycle, '_run', run)
    monkeypatch.setattr(lifecycle, '_llama_service', run)
    assert lifecycle.stop_run_process('local-code', data['run_id'])['stopped']
    run.assert_not_called()
    assert lifecycle.run_binding('local-code', data['run_id'])['stopped']
    assert channel.release(data['run_id'])
    assert reserve() is not None


def test_cancel_without_receipt_cannot_claim_stopped(cli, monkeypatch):
    data = reserve()
    event('UserPromptSubmit', prompt=marker(data))
    monkeypatch.setattr(lifecycle, '_run', Mock(return_value=SimpleNamespace(returncode=0)))
    monkeypatch.setattr(channel, 'wait_ack', Mock(side_effect=lifecycle.LifecycleError('cli_ack_timeout', 'sem ack')))
    with pytest.raises(lifecycle.LifecycleError):
        lifecycle.stop_run_process('local-code', data['run_id'])
    assert not lifecycle.run_binding('local-code', data['run_id'])['stopped']
    assert channel.read()['phase'] == 'cancelling'


def test_cancel_barrier_refuses_pending_tools(cli):
    data = reserve()
    event('UserPromptSubmit', prompt=marker(data))
    event('PreToolUse', tool_use_id='tool-1')
    with channel.channel_lock():
        state = channel.read()
        state['phase'] = 'cancelling'
        channel.save(state)
    event('UserPromptSubmit', prompt=marker(data, cancel=True))
    assert not channel.read().get('cancel_ack')
    event('PostToolUseFailure', tool_use_id='tool-1')
    event('UserPromptSubmit', prompt=marker(data, cancel=True))
    assert channel.read()['cancel_ack']


def test_background_work_never_releases(cli):
    data = reserve()
    event('UserPromptSubmit', prompt=marker(data))
    event('Stop', background_tasks=[{'id': 'bg', 'status': 'running'}])
    assert channel.read()['phase'] == 'uncertain'
    assert not channel.release(data['run_id'])


def test_stop_requires_native_idle_barrier(cli):
    data = reserve()
    event('UserPromptSubmit', prompt=marker(data))
    event('Stop')
    assert channel.read()['phase'] == 'finishing'
    assert not channel.release(data['run_id'])


def test_dead_cli_can_cancel_without_touching_replacement(cli, monkeypatch):
    data = reserve()
    monkeypatch.setattr(channel, 'identity_matches', lambda state: state.get('pid') == 99)
    monkeypatch.setattr(channel, 'previous_process_exited', lambda _: True)
    monkeypatch.setattr(channel, '_hook_identity', lambda: {'pid': 99, 'starttime': 'new'})
    channel.hook({'hook_event_name': 'SessionStart', 'session_id': 'replacement'})
    tmux = Mock()
    monkeypatch.setattr(lifecycle, '_run', tmux)
    assert channel.stop(data['run_id'])['stopped']
    assert channel.release(data['run_id'])
    assert channel.read()['pid'] == 99
    assert channel.read()['phase'] == 'idle'
    tmux.assert_not_called()


def test_dead_cli_with_orphan_tool_remains_quarantined(cli, monkeypatch):
    data = reserve()
    event('UserPromptSubmit', prompt=marker(data))
    event('PreToolUse', tool_use_id='possibly-live-child')
    monkeypatch.setattr(channel, 'identity_matches', lambda _: False)
    monkeypatch.setattr(channel, 'previous_process_exited', lambda _: True)
    with pytest.raises(lifecycle.LifecycleError, match='residual'):
        channel.stop(data['run_id'])
    assert not channel.release(data['run_id'])


def test_auto_launcher_refuses_parallel_local_session():
    from app.routers.terminal import start_agent_runtime
    with pytest.raises(RuntimeError, match='fila persistente'):
        start_agent_runtime('local-code', 'plano', run_id=uuid4())


def test_run_terminal_refuses_auxiliary_shell_without_binding(monkeypatch):
    from contextlib import nullcontext
    from app.routers import run_terminal
    from app.services.terminal_sessions import TerminalSessionError
    db = Mock()
    db.get.return_value = SimpleNamespace(agent='local-code', status='queued')
    monkeypatch.setattr(run_terminal, 'SessionLocal', lambda: nullcontext(db))
    monkeypatch.setattr(lifecycle, 'run_binding', lambda *args: None)
    create = Mock()
    monkeypatch.setattr(run_terminal.TerminalSessionManager, 'create', create)
    with pytest.raises(TerminalSessionError, match='canônico'):
        run_terminal._create_unlocked(str(uuid4()))
    create.assert_not_called()
