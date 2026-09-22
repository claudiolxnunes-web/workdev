"""Durable runtime contract. Readers never probe processes or retain a cache."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
import fcntl
import json
import logging
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError


PERSISTENT_AGENTS = frozenset({'claude', 'codex', 'local-code'})


def is_persistent(agent: str, session: str | None) -> bool:
    return agent in PERSISTENT_AGENTS and bool(session) and not session.startswith('auto-')


class RuntimeState(str, Enum):
    OFFLINE = 'OFFLINE'
    STARTING = 'STARTING'
    ONLINE = 'ONLINE'
    STOPPING = 'STOPPING'
    ERROR = 'ERROR'


class ActivityState(str, Enum):
    IDLE = 'IDLE'
    BUSY = 'BUSY'
    WAITING_INPUT = 'WAITING_INPUT'


class AgentSnapshot(BaseModel):
    model_config = ConfigDict(extra='ignore')
    agent: str
    runtime_state: RuntimeState
    activity_state: ActivityState
    checked_at: str
    reason: str | None = None
    persistent: bool = True
    process: str = ''
    active_run_id: str | None = None
    run_status: str | None = None
    activity_reason: str | None = None
    lifecycle: dict | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_file() -> Path:
    return Path(os.getenv('AGENTS_HEALTH_STATE', '/var/lib/agents-healthcheck/status.json'))


@contextmanager
def file_lock(path: Path, *, blocking: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o640)
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _semantic(row):
    return {'runtime': row['runtime_state'], 'activity': row['activity_state']}


def publish(rows: list[AgentSnapshot], path: Path | None = None, *, source='healthcheck'):
    """Confirmar, publicar e registrar sob o mesmo lock canônico.

    O journal integra o snapshot: estado novo e evento pendente são uma única
    escrita durável. PostgreSQL recebe UUIDs estáveis, permitindo replay após
    crash antes da limpeza do journal. Uma falha de banco não perde transições.
    """
    from app.services import runtime_state_audit
    from sqlalchemy.exc import SQLAlchemyError
    if source not in {'healthcheck', 'lifecycle'}:
        raise ValueError('invalid snapshot source')
    path = path or state_file()
    with file_lock(path.with_suffix('.lock')):
        try:
            payload = json.loads(path.read_text())
            if not isinstance(payload, dict):
                raise ValueError('invalid snapshot')
            if payload.get('version') != 2:
                if payload.get('version') == 1 and not payload.get('audit_pending'):
                    payload = {}  # Migração do snapshot legado, sem histórico v2.
                else:
                    raise ValueError('unsupported snapshot audit version')
        except FileNotFoundError:
            payload = {}
        except (ValueError, TypeError) as error:
            # Nunca descartar silenciosamente um journal potencialmente pendente.
            raise OSError('snapshot audit journal unreadable') from error
        agents = payload.setdefault('agents', {})
        candidates = payload.setdefault('audit_candidates', {})
        pending = payload.setdefault('audit_pending', [])
        if not isinstance(agents, dict) or not isinstance(candidates, dict) or not isinstance(pending, list):
            raise OSError('snapshot audit journal invalid')
        payload.setdefault('audit_sequence', 0)
        payload.setdefault('audit_stream', str(uuid4()))
        for row in rows:
            sample = row.model_dump(mode='json')
            stamp = datetime.fromisoformat(row.checked_at)
            if stamp.tzinfo is None:
                raise ValueError('snapshot timestamp must be timezone aware')
            old = agents.get(row.agent)
            candidate = candidates.get(row.agent)
            latest = candidate['last_sample'] if candidate else (old or {}).get('checked_at')
            if latest and stamp <= datetime.fromisoformat(latest):
                continue
            if old and source == 'healthcheck' and row.runtime_state in {RuntimeState.ERROR, RuntimeState.OFFLINE} and _semantic(old) != _semantic(sample):
                # Dois samples distintos e ao menos 10s. Nunca usar repetição de
                # publicação da mesma coleta como confirmação de falha.
                if not candidate or candidate['state'] != _semantic(sample):
                    candidates[row.agent] = {'state': _semantic(sample),
                        'since': row.checked_at, 'last_sample': row.checked_at}
                    continue
                candidate['last_sample'] = row.checked_at
                if (stamp - datetime.fromisoformat(candidate['since'])).total_seconds() < 10:
                    continue
            candidates.pop(row.agent, None)
            if old and _semantic(old) != _semantic(sample):
                current = datetime.now(timezone.utc)
                previous = payload.get('audit_timestamp')
                if previous:
                    current = max(current, datetime.fromisoformat(previous) + timedelta(microseconds=1))
                timestamp = current.isoformat()
                payload['audit_timestamp'] = timestamp
                payload['audit_sequence'] += 1
                event = {'runtime_id': row.agent, 'estado_anterior': _semantic(old),
                    'novo_estado': _semantic(sample), 'timestamp': timestamp,
                    'source': source, 'sequence': payload['audit_sequence'],
                    'stream_id': payload['audit_stream']}
                related_run = row.active_run_id or old.get('active_run_id')
                if related_run:
                    event['run_id'] = related_run
                if row.reason or row.activity_reason:
                    from app.services.context_redaction import redact
                    event['erro'] = redact(row.reason or row.activity_reason).text[:1000]
                pending.append({'event_id': str(uuid4()), 'payload': event})
            agents[row.agent] = sample
        payload.update(version=2, updated_at=now())
        atomic_json(path, payload)
        if pending:
            try:
                runtime_state_audit.persist(pending)
            except SQLAlchemyError:
                # Somente tipo fixo, nunca connection string/SQL/segredos.
                logging.getLogger(__name__).warning('runtime audit database unavailable; durable replay pending')
            else:
                payload['audit_pending'] = []
                atomic_json(path, payload)


def public_row(row: AgentSnapshot) -> dict:
    data = row.model_dump(mode='json')
    online = row.runtime_state == RuntimeState.ONLINE
    activity = row.activity_state
    health = ('busy' if activity == ActivityState.BUSY else 'blocked' if activity == ActivityState.WAITING_INPUT else 'idle') if online else (
        'offline' if row.runtime_state == RuntimeState.OFFLINE else 'degraded')
    data.update(
        running=online, checked=row.runtime_state != RuntimeState.ERROR,
        health=health, health_reason=row.reason,
        awaiting_approval=online and activity == ActivityState.WAITING_INPUT,
        approval_prompt=None, recovered=False,
        operational_status=(
            'awaiting_user' if online and activity == ActivityState.WAITING_INPUT else
            'blocked' if row.run_status == 'blocked' or row.activity_reason else
            'executing' if online and activity == ActivityState.BUSY else
            'awaiting_user' if row.run_status == 'review' else
            'completed' if row.run_status == 'completed' else
            'standby' if row.runtime_state == RuntimeState.OFFLINE or online else 'error'
        ),
    )
    return data


def read_snapshot(agent_ids, path: Path | None = None) -> dict:
    """One atomic file read per request, with per-row freshness and fail-closed schema."""
    reason = None
    updated_at = None
    agents = {}
    try:
        payload = json.loads((path or state_file()).read_text())
        if payload['version'] != 2 or not isinstance(payload['agents'], dict):
            raise ValueError('schema')
        agents = payload['agents']
        updated_at = payload['updated_at']
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        reason = 'snapshot_missing_or_invalid'
    rows = []
    current = datetime.now(timezone.utc)
    max_age = float(os.getenv('AGENTS_HEALTH_MAX_AGE_SECONDS', '45'))
    for agent in agent_ids:
        try:
            row = AgentSnapshot.model_validate(agents.get(agent))
            stamp = datetime.fromisoformat(row.checked_at)
            if row.agent != agent or stamp.tzinfo is None:
                raise ValueError('identity_or_timestamp')
            age = (current - stamp).total_seconds()
            if age > max_age or age < -5:
                row.runtime_state = RuntimeState.ERROR
                row.activity_state = ActivityState.IDLE
                row.reason = 'snapshot_stale'
        except (ValidationError, ValueError, TypeError):
            # Deterministic error snapshot too: no request-time timestamp.
            row = AgentSnapshot(agent=agent, runtime_state=RuntimeState.ERROR,
                activity_state=ActivityState.IDLE, checked_at='',
                reason=reason or 'agent_snapshot_invalid')
        rows.append(public_row(row))
    return {'version': 2, 'updated_at': updated_at, 'agents': rows}


def from_physical(agent: str, state, *, activity='IDLE', reason=None, checked_at=None):
    if not state.registry_ok or not state.model_state_known:
        runtime, reason = 'ERROR', 'physical_state_unknown'
    elif state.offline:
        runtime = 'OFFLINE'
    elif state.agent_process_running or (state.session is None and state.model_loaded):
        runtime = 'ONLINE'
    else:
        runtime, reason = 'ERROR', 'runtime_inconsistent'
    if reason and runtime == 'ONLINE':
        runtime = 'ERROR'
    return AgentSnapshot(agent=agent, runtime_state=runtime,
        activity_state=activity if runtime == 'ONLINE' else 'IDLE',
        checked_at=checked_at or now(), reason=reason,
        persistent=is_persistent(agent, state.session), process=state.current_process or '',
        active_run_id=(state.active_work or {}).get('run_id'), lifecycle=state.as_dict())
