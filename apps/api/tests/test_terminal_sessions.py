"""Real Linux PTYs; isolated persistence, no agent runtime or tmux involved."""
import os
from pathlib import Path
import signal
import sys
import time
import tempfile
from uuid import uuid4

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import sessionmaker

from app.models.terminal_session import TerminalSession
from app.services.terminal_sessions import TerminalSessionManager, TerminalSessionError
from app.services.terminal_worker import identity


@pytest.fixture
def terminal(tmp_path, monkeypatch):
    import app.services.terminal_sessions as service
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
    with tempfile.TemporaryDirectory(prefix='wdpty-') as runtime_dir, factory() as db:
        run = Run(); run.id = uuid4()
        db.add(run); db.commit()
        manager = TerminalSessionManager(db, runtime_dir)
        yield manager, run.id, factory
        try:
            manager.close(run.id)
        except TerminalSessionError:
            pass
    engine.dispose()


def wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.03)
    pytest.fail('condition timed out')


def test_create_persist_reattach_and_clean_close(terminal):
    manager, run_id, factory = terminal
    item = manager.create(run_id)
    pid, supervisor = item.pid, item.supervisor_pid
    assert item.state == 'RUNNING' and identity(pid) == item.process_identity
    assert Path(item.pty_path).exists()
    assert manager.create(run_id).pid == pid
    with factory() as other:
        restored = TerminalSessionManager(other, manager.root)
        assert restored.reattach(run_id)['pid'] == pid
        restored.write(run_id, 'printf "PTY_READY\\n"\n')
        wait_for(lambda: 'PTY_READY' in restored.reattach(run_id)['output'])
        assert restored.close(run_id).state == 'CLOSED'
        assert restored.close(run_id).state == 'CLOSED'
    wait_for(lambda: not Path(f'/proc/{pid}').exists())
    wait_for(lambda: not Path(f'/proc/{supervisor}').exists())
    assert not Path(item.socket_path).exists()
    assert manager.health(run_id).closed_at is not None


def test_natural_exit_is_reaped_and_persisted(terminal):
    manager, run_id, _ = terminal
    item = manager.create(run_id, [sys.executable, '-c', 'import time; time.sleep(.2); raise SystemExit(7)'])
    pid = item.pid
    wait_for(lambda: manager.health(run_id).state == 'CLOSED')
    assert item.exit_code == 7
    assert not Path(f'/proc/{pid}').exists()


def test_close_kills_ignoring_child_and_reaps_descendants(terminal):
    manager, run_id, _ = terminal
    item = manager.create(run_id, [sys.executable, '-c',
        'import os,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); '
        'pid=os.fork(); print("CHILD", pid, flush=True); time.sleep(60)'])
    output = wait_for(lambda: (data if 'CHILD' in (data := manager.reattach(run_id)['output']) else None))
    children = [int(line.split()[1]) for line in output.splitlines() if line.startswith('CHILD ') and line.split()[1] != '0']
    assert children
    assert manager.close(run_id).state == 'CLOSED'
    for pid in [item.pid, *children]:
        wait_for(lambda: not Path(f'/proc/{pid}').exists())


def test_forced_child_death_reconciles(terminal):
    manager, run_id, _ = terminal
    item = manager.create(run_id)
    os.kill(item.pid, signal.SIGKILL)
    wait_for(lambda: manager.health(run_id).state == 'CLOSED')
    assert item.exit_code == -signal.SIGKILL


def test_reject_unknown_run_and_bad_command(terminal):
    manager, _, _ = terminal
    with pytest.raises(TerminalSessionError, match='Run not found'):
        manager.create(uuid4())
    with pytest.raises(TerminalSessionError, match='argv'):
        manager.create(uuid4(), 'shell command')


def test_fk_and_unique_run_are_database_constraints(terminal):
    from sqlalchemy.exc import IntegrityError
    manager, run_id, factory = terminal
    manager.create(run_id)
    with factory() as db:
        for value in (run_id, uuid4()):
            db.add(TerminalSession(run_id=value, state='STARTING', socket_path='/unused', cwd='/tmp'))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()


def test_missing_supervisor_never_signals_unverified_pid(terminal, monkeypatch):
    manager, run_id, _ = terminal
    item = manager.create(run_id)
    manager.close(run_id)
    (manager.root / f'{item.id}.json').unlink()
    item.state = 'RUNNING'; manager.db.commit()
    monkeypatch.setattr(os, 'kill', lambda *args: pytest.fail('must not signal stale PID'))
    assert manager.health(run_id).state == 'ERROR'
    with pytest.raises(TerminalSessionError, match='unverified PID'):
        manager.close(run_id)


def test_close_reaps_descendant_that_created_its_own_session(terminal):
    manager, run_id, _ = terminal
    command = "import os,time; child=os.fork(); os.setsid() if child == 0 else None; print('ESCAPED', child, flush=True); time.sleep(60)"
    item = manager.create(run_id, [sys.executable, '-c', command])
    output = wait_for(lambda: (data if 'ESCAPED' in (data := manager.reattach(run_id)['output']) else None))
    children = [int(line.split()[1]) for line in output.splitlines() if line.startswith('ESCAPED ') and line.split()[1] != '0']
    assert children
    assert manager.close(run_id).state == 'CLOSED'
    for pid in [item.pid, *children]:
        wait_for(lambda: not Path(f'/proc/{pid}').exists())


def test_reattach_from_another_python_process(terminal):
    import subprocess
    manager, run_id, factory = terminal
    item = manager.create(run_id)
    script = """
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.services.terminal_sessions import TerminalSessionManager
with Session(create_engine(sys.argv[1])) as db:
    manager = TerminalSessionManager(db, sys.argv[2])
    print(manager.reattach(sys.argv[3])['pid'])
"""
    result = subprocess.run([sys.executable, '-c', script, str(factory.kw['bind'].url), str(manager.root), str(run_id)],
        cwd='/opt/workdev/apps/api', capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) == item.pid
    assert manager.health(run_id).state == 'RUNNING'
