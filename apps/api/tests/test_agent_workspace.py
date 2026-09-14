"""Workspace isolation and failure ordering; real tmux runs in a private socket."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from app.services import agent_lifecycle as lifecycle, agent_workspace as workspace


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle, 'GROUPS_FILE', tmp_path / 'groups.json')
    return lifecycle.GROUPS_FILE


def test_missing_binding_never_signals(registry, monkeypatch):
    signal = Mock()
    monkeypatch.setattr(lifecycle, 'terminate_group', signal)
    with pytest.raises(lifecycle.LifecycleError, match='legada'):
        lifecycle.stop_run_process('kimi', uuid4())
    signal.assert_not_called()


def test_binding_agent_mismatch_refuses(registry):
    run = uuid4()
    lifecycle._save_run_binding(run, {'agent': 'kimi'})
    with pytest.raises(lifecycle.LifecycleError, match='outro agente'):
        lifecycle.run_binding('codex', run)


def test_pid_reuse_never_signals(registry, monkeypatch):
    run = uuid4()
    lifecycle._save_run_binding(run, dict(agent='kimi', pid=42, starttime='old', stopped=False))
    monkeypatch.setattr(lifecycle, 'process_starttime', lambda _: 'new')
    signal = Mock()
    monkeypatch.setattr(lifecycle, 'terminate_group', signal)
    with pytest.raises(lifecycle.LifecycleError, match='reutilizado'):
        lifecycle.stop_run_process('kimi', run)
    signal.assert_not_called()


def test_tombstone_survives_new_reader(registry):
    run = uuid4()
    lifecycle._save_run_binding(run, dict(agent='kimi', stopped=True, session='gone'))
    assert json.loads(registry.read_text())['runs'][str(run)]['stopped']
    assert lifecycle.stop_run_process('kimi', run)['already_stopped']


@pytest.fixture
def stop_workflow(registry, monkeypatch):
    run = SimpleNamespace(id=uuid4(), agent='kimi', status='running')
    db = Mock()
    steps = []
    monkeypatch.setattr(workspace, 'audit', lambda action, **kw: steps.append(kw['result'] if 'result' in kw else 'requested'))
    monkeypatch.setattr(lifecycle, 'stop_run_process', lambda *args: steps.append('physical') or {'stopped': True})
    terminal_db = Mock()
    terminal_db.query.return_value.filter_by.return_value.first.return_value = None
    @contextmanager
    def factory():
        yield terminal_db
    monkeypatch.setattr(workspace, 'SessionLocal', factory)
    def update(db, run, data):
        steps.append('persist')
        run.status = data['status']
        lifecycle._save_run_binding(run.id, {'agent': run.agent, 'stopped': True, 'session': 'gone'})
        return run, None
    monkeypatch.setattr(workspace, 'update_run', update)
    return run, db, steps


def test_stop_orders_physical_before_persistence_and_is_idempotent(stop_workflow):
    run, db, steps = stop_workflow
    workspace.stop_run(db, run)
    assert steps == ['requested', 'physical', 'persist', 'succeeded']
    workspace.stop_run(db, run)
    assert steps == ['requested', 'physical', 'persist', 'succeeded']


def test_stop_failure_keeps_workflow_running(stop_workflow, monkeypatch):
    run, db, steps = stop_workflow
    def fail(*args):
        raise lifecycle.LifecycleError('survivors', 'Processo vivo')
    monkeypatch.setattr(lifecycle, 'stop_run_process', fail)
    with pytest.raises(lifecycle.LifecycleError):
        workspace.stop_run(db, run)
    assert run.status == 'running' and 'persist' not in steps
    assert steps == ['requested', 'failed']
    db.rollback.assert_called_once()


def test_persistence_failure_is_audited_without_restart(stop_workflow, monkeypatch):
    run, db, steps = stop_workflow
    def fail(*args):
        raise RuntimeError('DB unavailable')
    monkeypatch.setattr(workspace, 'update_run', fail)
    with pytest.raises(RuntimeError):
        workspace.stop_run(db, run)
    assert steps == ['requested', 'physical', 'failed']
    assert run.status == 'running'


def test_invalid_transition_does_not_touch_process(stop_workflow):
    run, db, steps = stop_workflow
    run.status = 'completed'
    with pytest.raises(workspace.HandoffError):
        workspace.stop_run(db, run)
    assert not steps


def test_projection_preserves_snapshot_not_database_online():
    run = SimpleNamespace(id=uuid4(), agent='kimi', backlog_id=uuid4(), status='running')
    db = Mock()
    db.query.return_value.join.return_value.filter.return_value.order_by.return_value.all.return_value = [(run, 'Task')]
    snapshot = {'version': 2, 'agents': [{'agent': 'kimi', 'runtime_state': 'OFFLINE', 'activity_state': 'IDLE'}]}
    response = workspace.enrich(snapshot, db)
    assert response['agents'][0]['runtime_state'] == 'OFFLINE'
    assert response['agents'][0]['runs'][0]['id'] == str(run.id)
    assert 'runs' not in snapshot['agents'][0]


def test_real_tmux_exact_run_stop_preserves_neighbor_and_standby(registry, monkeypatch):
    socket = 'workspace-test-' + uuid4().hex[:12]
    original = lifecycle._run
    def command(argv, timeout=10):
        if argv[0] == 'tmux':
            argv = ['tmux', '-L', socket, *argv[1:]]
        return original(argv, timeout)
    monkeypatch.setattr(lifecycle, '_run', command)
    monkeypatch.setattr(lifecycle, 'GRACEFUL_TIMEOUT_SECONDS', .2)
    run, other = uuid4(), uuid4()
    target, neighbor = f'auto-kimi-{run}', f'auto-kimi-{other}'
    try:
        for session in (target, neighbor, 'kimi'):
            result = command(['tmux', 'new-session', '-d', '-s', session, 'sleep', '120'])
            assert result.returncode == 0, result.stderr
        with lifecycle.run_lock(run), lifecycle.agent_lock('kimi'):
            binding = lifecycle.bind_run('kimi', run, target)
        assert os.stat(f"/proc/{binding['pid']}").st_uid == os.getuid()
        # Simultaneous callers serialize at the same boundary used by HTTP stop.
        def stop():
            with lifecycle.run_lock(run):
                return lifecycle.stop_run_process('kimi', run)
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: stop(), range(3)))
        assert all(row['stopped'] for row in results)
        assert not lifecycle.session_exists(target)
        assert lifecycle.session_exists(neighbor)
        assert lifecycle.session_exists('kimi')
        assert lifecycle.run_binding('kimi', run)['stopped']
    finally:
        command(['tmux', 'kill-server'])
