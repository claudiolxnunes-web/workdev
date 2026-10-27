"""Read-only repository snapshots for the optional Run Observer."""

import hashlib
import os
import subprocess
from pathlib import Path

from app.models.handoff import AgentRun, AgentRunEvent
from app.services.build_worktree import repo_root
from app.services.observer_selection import current


SNAPSHOT = 'observer.workspace_snapshot'


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(['git', *args], cwd=root, capture_output=True,
        timeout=10, check=False, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    if result.returncode:
        raise RuntimeError('Snapshot Git indisponível')
    return result.stdout


def snapshot(root: Path | None = None) -> dict:
    """Return only a fingerprint and safe path names; never persist file text."""
    root = (root or repo_root()).resolve()
    head = _git(root, 'rev-parse', 'HEAD').decode().strip()
    changed = set(_git(root, 'diff', '--name-only', '-z', 'HEAD').decode().split('\0'))
    changed.update(_git(root, 'ls-files', '--others', '--exclude-standard', '-z').decode().split('\0'))
    paths = sorted(path for path in changed if path and not any(
        part.startswith('.env') or part.endswith(('.pem', '.key'))
        for part in Path(path).parts))
    digest = hashlib.sha256(head.encode())
    for name in paths:
        digest.update(name.encode())
        path = root / name
        try:
            if path.is_symlink():
                digest.update(b'symlink-skipped')
                continue
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                digest.update(b'missing-or-unsafe')
                continue
            size = resolved.stat().st_size
            if size > 2_000_000:
                digest.update(f'large:{size}:{resolved.stat().st_mtime_ns}'.encode())
            else:
                digest.update(hashlib.sha256(resolved.read_bytes()).digest())
        except (OSError, RuntimeError):
            digest.update(b'unreadable')
    return {'fingerprint': digest.hexdigest(), 'head': head, 'paths': paths[:200],
            'paths_truncated': len(paths) > 200, 'diff_truncated': len(paths) > 200}


def baseline(db, run):
    try:
        data = snapshot()
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return None
    db.add(AgentRunEvent(run_id=run.id, event_type=SNAPSHOT,
        message='Base de leitura do Observer', payload=data))
    return data


def poll(db, *, limit=100) -> int:
    """Only active, explicitly selected runs; no change emits no LLM event."""
    checked = 0
    runs = db.query(AgentRun).filter(AgentRun.status == 'running').limit(limit).all()
    data = None
    for run in runs:
        choice = current(db, run.id)
        if not choice or not choice['enabled']:
            continue
        if data is None:
            try:
                data = snapshot()
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                return checked
        previous = (db.query(AgentRunEvent).filter_by(run_id=run.id, event_type=SNAPSHOT)
                    .order_by(AgentRunEvent.created_at.desc(), AgentRunEvent.id.desc()).first())
        if previous is None:
            db.add(AgentRunEvent(run_id=run.id, event_type=SNAPSHOT,
                message='Base de leitura do Observer', payload=data))
            checked += 1
            continue
        if data['fingerprint'] != (previous.payload or {}).get('fingerprint'):
            db.add(AgentRunEvent(run_id=run.id, event_type='file_changed',
                message='Mudança relevante detectada na árvore de trabalho',
                payload={'from_fingerprint': (previous.payload or {}).get('fingerprint'),
                         **data}))
            db.add(AgentRunEvent(run_id=run.id, event_type=SNAPSHOT,
                message='Snapshot após mudança', payload=data))
        checked += 1
    db.commit()
    return checked
