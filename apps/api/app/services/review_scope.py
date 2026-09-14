"""Limites persistidos da mudança: base da execução, nunca develop móvel."""
import re
from uuid import UUID

from app.models.handoff import AgentRunEvent
from app.services.build_worktree import head_sha, repo_root

BASE_EVENT = 'build.review_baseline'


def valid_sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{40}', value) is not None


def load_base(db, run_id, seen=None):
    seen = set() if seen is None else seen
    if run_id in seen or len(seen) >= 20:
        return None
    seen.add(run_id)
    events = (db.query(AgentRunEvent).filter(AgentRunEvent.run_id == run_id,
              AgentRunEvent.event_type.in_((BASE_EVENT, 'build.committed', 'build.transferred')))
              .order_by(AgentRunEvent.created_at.asc()).all())
    # Transfers carry the original task scope, including earlier executors.
    for event in events:
        payload = event.payload or {}
        if event.event_type == 'build.transferred':
            try:
                return load_base(db, UUID(payload['from_run_id']), seen)
            except (ValueError, KeyError, TypeError):
                return None
    for event in events:
        base = (event.payload or {}).get('base_sha')
        if valid_sha(base):
            return base
    return None


def capture_start_base(db, run):
    """Caller must invoke only before the first queued → running transition."""
    if load_base(db, run.id):
        return
    # Do not invent a new baseline for an inherited/legacy execution.
    transferred = db.query(AgentRunEvent).filter(
        AgentRunEvent.run_id == run.id,
        AgentRunEvent.event_type == 'build.transferred').first()
    if transferred:
        return
    try:
        base = head_sha(repo_root())
    except Exception:
        return  # The review policy fails closed if the base is unavailable.
    if valid_sha(base):
        db.add(AgentRunEvent(run_id=run.id, event_type=BASE_EVENT,
                            message='Base imutável capturada antes do primeiro início',
                            payload={'base_sha': base, 'repository': str(repo_root())}))
        db.flush()


def diff_summary(run, root=None):
    """Numstat only: no full patch is materialized by the minimal context GET."""
    import subprocess
    root = root or repo_root()
    base = getattr(run, 'review_base_sha', None)
    target = getattr(run, 'commit_sha', None)
    if not valid_sha(base) or not valid_sha(target):
        return None
    try:
        ancestor = subprocess.run(['git', 'merge-base', '--is-ancestor', base, target],
                                  cwd=root, capture_output=True, timeout=30)
        if ancestor.returncode:
            return None
        result = subprocess.run(['git', 'diff', '--no-renames', '--numstat', '-z', base, target],
                                cwd=root, capture_output=True, text=True, timeout=30)
        if result.returncode:
            return None
        files, lines = [], 0
        for record in result.stdout.split('\0'):
            if not record:
                continue
            added, removed, name = record.split('\t', 2)
            files.append(name)
            if added != '-' and removed != '-':
                lines += int(added) + int(removed)
        return files, lines
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
