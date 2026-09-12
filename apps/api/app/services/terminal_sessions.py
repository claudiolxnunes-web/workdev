"""Persistent Linux terminal lifecycle. Each public operation owns its DB transaction.

Use a dedicated Session, not one with unrelated pending writes. The worker owns
its PTY; recreating this manager does not recreate the terminal. Call health to
reconcile an exited worker with its durable result. No background health loop.
"""
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.models.handoff import AgentRun
from app.models.terminal_session import TerminalSession
from app.services.terminal_worker import identity


class TerminalSessionError(RuntimeError):
    pass


class TerminalSessionManager:
    def __init__(self, db, root=None):
        self.db = db
        self.root = Path(root or os.getenv('WORKDEV_TERMINAL_DIR', '/tmp/workdev-terminals'))
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if self.root.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise TerminalSessionError('Terminal directory must be private and owned by runtime user')

    def _session(self, run_id):
        item = self.db.query(TerminalSession).filter_by(run_id=UUID(str(run_id))).populate_existing().first()
        if not item:
            raise TerminalSessionError('Run has no terminal session')
        return item

    def _request(self, item, op, **kwargs):
        path = self.root / f'{item.id}.sock'
        if str(path) != item.socket_path:
            raise TerminalSessionError('Terminal directory differs from persisted session')
        with socket.socket(socket.AF_UNIX) as conn:
            conn.settimeout(2)
            conn.connect(str(path))
            conn.sendall(json.dumps(dict(id=str(item.id), op=op, **kwargs)).encode() + b'\n')
            data = bytearray()
            while b'\n' not in data and len(data) < 524288:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data.extend(chunk)
            response = json.loads(data)
        if response.get('error'):
            raise TerminalSessionError(response['error'])
        return response

    def create(self, run_id, argv=None, cwd=None):
        argv = argv or ['/bin/bash', '--noprofile', '--norc']
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and '\x00' not in x for x in argv):
            raise TerminalSessionError('argv must be a nonempty list of strings')
        cwd = str(Path(cwd or '/opt/workdev').resolve(strict=True))
        run_id = UUID(str(run_id))
        run = self.db.query(AgentRun).filter_by(id=run_id).with_for_update().first()
        if not run:
            raise TerminalSessionError('Run not found')
        existing = self.db.query(TerminalSession).filter_by(run_id=run_id).first()
        if existing:
            self.db.commit()
            return self.health(run_id)
        if len(os.fsencode(str(self.root / ('0' * 36 + '.sock')))) >= 108:
            self.db.rollback()
            raise TerminalSessionError('Terminal socket path exceeds Linux limit')
        session_id = uuid4()
        item = TerminalSession(id=session_id, run_id=run_id, state='STARTING', cwd=cwd,
                               socket_path=str(self.root / f'{session_id}.sock'))
        self.db.add(item)
        self.db.commit()  # Record intent BEFORE starting physical work.
        worker = None
        try:
            # Deliberately do not pass database/API credentials to terminal processes.
            env = {'PATH': os.defpath, 'HOME': str(Path.home()), 'TERM': 'xterm-256color', 'LANG': 'C.UTF-8'}
            worker = subprocess.Popen([sys.executable, str(Path(__file__).with_name('terminal_worker.py'))],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, start_new_session=True, close_fds=True, env=env)
            worker.stdin.write(json.dumps(dict(id=str(item.id), socket_path=item.socket_path, cwd=cwd, argv=argv)) + '\n')
            worker.stdin.close()
            if not select.select([worker.stdout], [], [], 5)[0]:
                raise TerminalSessionError('PTY startup timed out')
            state = json.loads(worker.stdout.readline())
            worker.stdout.close()
            # Only reaps our supervisor; runtime state remains in DB/socket, not this thread.
            threading.Thread(target=worker.wait, daemon=True).start()
            self._apply(item, state)
            self.db.commit()
            return item
        except Exception as exc:
            if worker is not None:
                worker.terminate()
                try:
                    worker.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait()
            self.db.rollback()
            item = self._session(run_id)
            item.state, item.error = 'ERROR', f'PTY startup failed: {type(exc).__name__}'
            self.db.commit()
            raise TerminalSessionError(item.error) from exc

    def _apply(self, item, state):
        if state.get('id') != str(item.id):
            raise TerminalSessionError('Session identity mismatch')
        for field in ('pid', 'supervisor_pid', 'process_identity', 'pty_path'):
            old, new = getattr(item, field), state.get(field)
            if old is not None and old != new:
                raise TerminalSessionError('Process identity changed')
            setattr(item, field, new)
        item.state = state['state']
        item.exit_code = state.get('exit_code')
        item.error = state.get('error')
        if item.state == 'CLOSED':
            item.closed_at = item.closed_at or datetime.now(timezone.utc)

    def health(self, run_id):
        item = self._session(run_id)
        try:
            state = self._request(item, 'health')
            self._apply(item, state)
            if identity(item.pid) != item.process_identity or not Path(item.pty_path).exists():
                raise TerminalSessionError('PID/PTY is no longer alive')
            item.error = None
        except (OSError, ValueError, TerminalSessionError) as exc:
            result = self.root / f'{item.id}.json'
            if result.exists():
                self._apply(item, json.loads(result.read_text()))
            elif item.state not in {'CLOSED', 'STOPPING'}:
                item.state, item.error = 'ERROR', f'Terminal unavailable: {type(exc).__name__}'
        self.db.commit()
        return item

    def reattach(self, run_id):
        item = self.health(run_id)
        if item.state != 'RUNNING':
            raise TerminalSessionError(f'Terminal is {item.state}')
        return self._request(item, 'health')

    def write(self, run_id, text):
        item = self.health(run_id)
        if item.state != 'RUNNING':
            raise TerminalSessionError(f'Terminal is {item.state}')
        if not isinstance(text, str) or len(text.encode()) > 4096:
            raise TerminalSessionError('Write limited to 4096 bytes')
        return self._request(item, 'write', text=text)['written']

    def close(self, run_id):
        item = self.health(run_id)
        if item.state == 'CLOSED':
            return item
        item.state = 'STOPPING'
        self.db.commit()
        try:
            self._request(item, 'close')
        except (OSError, ValueError) as exc:
            item.state, item.error = 'ERROR', 'Supervisor unavailable; refusing to signal an unverified PID'
            self.db.commit()
            raise TerminalSessionError(item.error) from exc
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (self.root / f'{item.id}.json').exists():
                return self.health(run_id)
            time.sleep(.02)
        raise TerminalSessionError('Terminal cleanup not yet complete; state remains STOPPING')

    stop = close
