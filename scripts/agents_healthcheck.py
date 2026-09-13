#!/opt/workdev/apps/api/venv/bin/python
"""Supervisiona as sessões tmux dos agentes sem expor credenciais."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout


WORKDEV_DIR = Path(os.environ.get("WORKDEV_DIR", str(Path(__file__).resolve().parents[1])))
STATE_FILE = Path(os.environ.get("AGENTS_HEALTH_STATE", "/var/lib/agents-healthcheck/status.json"))
ALERT_ENV = Path(os.environ.get("AGENTS_ALERT_ENV", "/opt/scripts/alerta.env"))
LOG_TAG = "agents-healthcheck"
sys.path.insert(0, str(WORKDEV_DIR / 'apps/api'))
from app.services import agent_snapshot, agent_lifecycle, agent_runtimes
from app.services.agent_activity import approval_lines


AGENTS = {
    "claude": ("code", [str(WORKDEV_DIR / "scripts/start_claude_agent.sh")]),
    "codex": ("codex", [str(WORKDEV_DIR / "scripts/start_codex_agent.sh")]),
    "kimi": ("kimi",["env", "KIMI_PROVIDER=openrouter", str(WORKDEV_DIR / "scripts/start_kimi_agent.sh")],
    ),
    "qwen": ("qwen", [str(WORKDEV_DIR / "scripts/start_qwen_agent.sh")]),
    "gemini": ("gemini", [str(WORKDEV_DIR / "scripts/start_gemini_agent.sh")]),
}
ALWAYS_ON_AGENTS = agent_snapshot.PERSISTENT_AGENTS

SHELL_PROCESSES = {"bash", "dash", "fish", "sh", "tmux", "zsh"}
BLOCKED_PATTERNS = (
    (re.compile(r"^(?:error[: ]+)?(?:401\s+)?(?:authentication (?:failed|error)|missing authentication)(?:\s|$)", re.I), "authentication"),
    (re.compile(r"^(?:error[: ]+)?(?:429\s+)?(?:account suspended due to insufficient balance|insufficient balance|recharge your account)(?:\s|$)", re.I), "billing"),
    (re.compile(r"api key.*(?:missing|invalid)|(?:missing|invalid).*api key", re.I), "api_key"),
)
BUSY_PATTERNS = (
    re.compile(r"working\s*\(|thinking\.{0,3}\s*\(|esc to interrupt|esc to cancel|ctrl\+c to cancel|press esc to interrupt", re.I),
)


@dataclass
class AgentHealth:
    agent: str
    session: str
    status: str
    process: str
    reason: str | None
    checked_at: str
    recovered: bool = False


def run(command: Sequence[str], timeout: int = 5) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def capture_recent(session: str, lines: int = 40) -> str:
    result = run(["tmux", "capture-pane", "-p", "-J", "-S", f"-{lines}", "-t", f"={session}:"])
    return result.stdout if result.returncode == 0 else ""


def classify(agent: str, session: str, process: str, output: str, checked_at: str) -> AgentHealth:
    if not process or process in SHELL_PROCESSES:
        return AgentHealth(agent, session, "offline", process, "agent_process_missing", checked_at)
    recent = "\n".join(output.splitlines()[-25:])
    for pattern, reason in BLOCKED_PATTERNS:
        if any(pattern.search(line.strip()) for line in recent.splitlines()):
            return AgentHealth(agent, session, "blocked", process, reason, checked_at)
    if approval_lines(output):
        return AgentHealth(agent, session, "waiting_input", process, None, checked_at)
    if any(pattern.search(recent) for pattern in BUSY_PATTERNS):
        return AgentHealth(agent, session, "busy", process, None, checked_at)
    return AgentHealth(agent, session, "idle", process, None, checked_at)


def collect_agent(agent: str, session: str | None, db, allow_restart=False, work=None, run_status=None):
    checked_at = agent_snapshot.now()
    operation = agent_lifecycle.read_operation(agent)
    try:
        state = agent_lifecycle.read_state(agent, session, db=db)
        if allow_restart and state.offline and not state.session_exists:
            recovery = agent_lifecycle.try_recover(agent, session, AGENTS[agent][1])
            if recovery is not None:
                state = agent_lifecycle.read_state(agent, session, db=db)
                checked_at = agent_snapshot.now()
            operation = agent_lifecycle.read_operation(agent)
        if work is not None:
            state.active_work = work
        activity, reason = 'IDLE', None
        if session and state.agent_process_running:
            health = classify(agent, session, state.current_process,
                capture_recent(session), checked_at)
            activity = {'busy': 'BUSY', 'waiting_input': 'WAITING_INPUT'}.get(health.status, 'IDLE')
            # Terminal text is activity evidence, not proof of physical failure.
            reason = health.reason
        # Persisted runs contribute activity only after physical availability.
        if state.active_work and activity != 'WAITING_INPUT':
            activity = 'BUSY'
        row = agent_snapshot.from_physical(agent, state, activity=activity, checked_at=checked_at)
        row.activity_reason = reason
        row.run_status = run_status
        phase = operation.get('phase')
        if phase in {'STARTING', 'STOPPING'}:
            if agent_lifecycle.operation_active(operation):
                row.runtime_state = agent_snapshot.RuntimeState(phase)
                row.activity_state = agent_snapshot.ActivityState.IDLE
                row.reason = None
            elif row.runtime_state.value != operation.get('desired'):
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(operation['updated_at'])).total_seconds()
                pending = not operation.get('running', True) and age < 60
                row.runtime_state = agent_snapshot.RuntimeState(phase if pending else 'ERROR')
                row.activity_state = agent_snapshot.ActivityState.IDLE
                row.reason = None if pending else 'lifecycle_interrupted'
        elif phase == 'ERROR' and operation_error_is_current(operation):
            row.runtime_state = agent_snapshot.RuntimeState.ERROR
            row.activity_state = agent_snapshot.ActivityState.IDLE
            row.reason = operation.get('reason') or 'lifecycle_failed'
        # A completed disconnect suppresses automatic restart, but cannot
        # override a later legitimate manual start. Physical evidence wins.
        return row
    except Exception as error:
        return agent_snapshot.AgentSnapshot(agent=agent, runtime_state='ERROR',
            activity_state='IDLE', checked_at=checked_at,
            reason=type(error).__name__, persistent=agent_snapshot.is_persistent(agent, session))


def operation_error_is_current(operation):
    if operation.get('reason') == 'operation_unreadable':
        return True
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(operation['updated_at'])).total_seconds()
        return age < 60
    except (KeyError, ValueError, TypeError):
        return True


def load_run_context(db):
    """Three batched queries per collection, never shared across probe threads."""
    from app.models.handoff import AgentRun, AgentBuildJob
    runs = db.query(AgentRun).distinct(AgentRun.agent).order_by(AgentRun.agent, AgentRun.created_at.desc()).all()
    statuses = {row.agent: row.status for row in runs}
    work = {row.agent: {'run_id': str(row.id), 'status': row.status, 'reason': 'run_running'}
        for row in db.query(AgentRun).filter(AgentRun.status == 'running').all()}
    jobs = db.query(AgentBuildJob, AgentRun.agent).join(AgentRun, AgentRun.id == AgentBuildJob.run_id).filter(
        AgentBuildJob.state.in_(agent_lifecycle.ACTIVE_JOB_STATES)).all()
    for job, agent in jobs:
        work.setdefault(agent, {'run_id': str(job.run_id), 'job_id': str(job.id),
            'status': job.state, 'reason': 'dispatch_active'})
    return statuses, work


def collect_snapshot(db, allow_restart=False, *, publish_rows=None, budget=25):
    statuses, work = load_run_context(db) if db is not None else ({}, {})
    entities = {agent: session for agent, (session, _) in AGENTS.items()}
    entities.update({runtime.id: None for runtime in agent_runtimes.RUNTIMES})
    rows = []
    # Parallel probes within the sole collector; no background loop or RAM cache.
    # A slow remote GPU never delays publication of healthy CLI agents.
    pool = ThreadPoolExecutor(max_workers=len(entities))
    pending = {pool.submit(collect_agent, agent, session, None,
        allow_restart and agent in ALWAYS_ON_AGENTS, work.get(agent), statuses.get(agent)): agent
        for agent, session in entities.items()}
    try:
        for future in as_completed(pending, timeout=budget):
            row = future.result()
            rows.append(row)
            if publish_rows:
                publish_rows([row])
            del pending[future]
    except FuturesTimeout:
        for future, agent in pending.items():
            future.cancel()
            row = agent_snapshot.AgentSnapshot(agent=agent, runtime_state='ERROR',
                activity_state='IDLE', checked_at=agent_snapshot.now(), reason='collection_timeout',
                persistent=agent_snapshot.is_persistent(agent, entities[agent]))
            rows.append(row)
            if publish_rows:
                publish_rows([row])
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return rows


def write_state(health):
    agent_snapshot.publish(health, STATE_FILE)


def read_previous_state() -> dict[str, dict]:
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        agents = payload.get("agents", {})
        return agents if isinstance(agents, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def read_alert_config() -> tuple[str, str] | None:
    try:
        values: dict[str, str] = {}
        for raw_line in ALERT_ENV.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() in {"TG_TOKEN", "TG_CHAT"}:
                parsed = shlex.split(value.strip(), comments=True)
                values[name.strip()] = parsed[0] if parsed else ""
        if values.get("TG_TOKEN") and values.get("TG_CHAT"):
            return values["TG_TOKEN"], values["TG_CHAT"]
    except (OSError, ValueError):
        pass
    return None


def send_alert(message: str) -> None:
    config = read_alert_config()
    if not config:
        return
    token, chat = config
    data = urllib.parse.urlencode({"chat_id": chat, "text": message}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=2):
            pass
    except OSError:
        run(["logger", "-t", LOG_TAG, "falha ao enviar alerta do supervisor"], timeout=2)


def notify_transitions(previous, health) -> None:
    ledger = STATE_FILE.with_name('notifications.json')
    stamp = datetime.now(timezone.utc).timestamp()
    with agent_snapshot.file_lock(ledger.with_suffix('.lock')):
        try:
            records = json.loads(ledger.read_text())
            if not isinstance(records, dict):
                records = {}
        except (OSError, ValueError):
            records = {}
        sent = False
        for item in health:
            if item.runtime_state.value not in {'ERROR', 'OFFLINE', 'ONLINE'}:
                continue
            # ERROR/OFFLINE are one failure class, so flapping between them
            # neither resets debounce nor produces repeated Telegram messages.
            current = 'down' if item.runtime_state.value in {'ERROR', 'OFFLINE'} else 'up'
            entry = records.get(item.agent)
            if not isinstance(entry, dict) or not {'observed', 'since', 'notified', 'last_sent'} <= entry.keys():
                entry = records[item.agent] = {'observed': current, 'since': stamp,
                    'notified': 'up', 'last_sent': 0}
            if entry['observed'] != current:
                entry.update(observed=current, since=stamp)
            if (sent or current == entry['notified'] or stamp - entry['since'] < 10
                    or stamp - entry['last_sent'] < 300):
                continue
            send_alert(f"[agents-healthcheck] {item.agent}: {item.runtime_state.value} ({item.reason or 'estado confirmado'}).")
            entry.update(notified=current, last_sent=stamp)
            sent = True
        agent_snapshot.atomic_json(ledger, records)


def health_exit_code(health) -> int:
    return int(any(row.agent in ALWAYS_ON_AGENTS and row.runtime_state.value in {'OFFLINE', 'ERROR'} for row in health))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="executa uma única verificação")
    parser.add_argument("--no-restart", action="store_true", help="não recupera sessões offline")
    args = parser.parse_args()
    # One systemd timer and one process-wide file lock. No API polling loop.
    os.environ.setdefault('WORKDEV_API_ENV_FILE', os.getenv('WORKDEV_ENV_FILE', '/etc/workdev/workdev-api.env'))
    from app.database import SessionLocal
    with agent_snapshot.file_lock(STATE_FILE.with_suffix('.collector.lock')):
        previous = read_previous_state()
        with SessionLocal() as db:
            # Bound DB work before probes start; no probe worker holds a DB connection.
            from sqlalchemy import text
            db.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            health = collect_snapshot(db, allow_restart=not args.no_restart, publish_rows=write_state)
        write_state(health)
    notify_transitions(previous, health)
    for item in health:
        print(f"{item.agent}: {item.runtime_state.value}/{item.activity_state.value}")
    return health_exit_code(health)


if __name__ == "__main__":
    raise SystemExit(main())
