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


WORKDEV_DIR = Path(os.environ.get("WORKDEV_DIR", "/opt/workdev"))
STATE_FILE = Path(os.environ.get("AGENTS_HEALTH_STATE", "/var/lib/agents-healthcheck/status.json"))
ALERT_ENV = Path(os.environ.get("AGENTS_ALERT_ENV", "/opt/scripts/alerta.env"))
LOG_TAG = "agents-healthcheck"
sys.path.insert(0, str(WORKDEV_DIR / 'apps/api'))
from app.services import agent_snapshot, agent_lifecycle, agent_runtimes


AGENTS = {
    "claude": ("code", [str(WORKDEV_DIR / "scripts/start_claude_agent.sh")]),
    "codex": ("codex", [str(WORKDEV_DIR / "scripts/start_codex_agent.sh")]),
    "kimi": ("kimi",["env", "KIMI_PROVIDER=openrouter", str(WORKDEV_DIR / "scripts/start_kimi_agent.sh")],
    ),
    "qwen": ("qwen", [str(WORKDEV_DIR / "scripts/start_qwen_agent.sh")]),
    "gemini": ("gemini", [str(WORKDEV_DIR / "scripts/start_gemini_agent.sh")]),
}
ALWAYS_ON_AGENTS = frozenset({"claude", "codex"})

SHELL_PROCESSES = {"bash", "dash", "fish", "sh", "tmux", "zsh"}
BLOCKED_PATTERNS = (
    (re.compile(r"\b401\b|auth(?:entication)?[_ ]error|missing authentication", re.I), "authentication"),
    (re.compile(r"\b429\b|insufficient balance|recharge your account|billing", re.I), "billing"),
    (re.compile(r"api key.*(?:missing|invalid)|(?:missing|invalid).*api key", re.I), "api_key"),
)
WAITING_PATTERNS = (
    re.compile(r'allow (?:execution|once|this)|do you (?:want|wish) to (?:proceed|allow)|would you like to proceed|approve this|waiting for (?:input|approval)|aguardando (?:aprovação|entrada)|yes, (?:proceed|allow)', re.I),
)
BUSY_PATTERNS = (
    re.compile(r"working\s*\(|esc to interrupt|ctrl\+c to cancel|press esc to interrupt", re.I),
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
        if pattern.search(recent):
            return AgentHealth(agent, session, "blocked", process, reason, checked_at)
    if any(pattern.search('\n'.join(output.splitlines()[-8:])) for pattern in WAITING_PATTERNS):
        return AgentHealth(agent, session, "waiting_input", process, None, checked_at)
    if any(pattern.search(recent) for pattern in BUSY_PATTERNS):
        return AgentHealth(agent, session, "busy", process, None, checked_at)
    return AgentHealth(agent, session, "idle", process, None, checked_at)


def collect_agent(agent: str, session: str | None, db, allow_restart=False):
    checked_at = agent_snapshot.now()
    operation = agent_lifecycle.read_operation(agent)
    try:
        state = agent_lifecycle.read_state(agent, session, db=db)
        if (allow_restart and state.offline and not state.session_exists
                and not operation):
            agent_lifecycle.start(agent, session, AGENTS[agent][1])
            state = agent_lifecycle.read_state(agent, session, db=db)
            checked_at = agent_snapshot.now()
        activity, reason = 'IDLE', None
        if session and state.agent_process_running:
            health = classify(agent, session, state.current_process,
                capture_recent(session), checked_at)
            activity = {'busy': 'BUSY', 'waiting_input': 'WAITING_INPUT'}.get(health.status, 'IDLE')
            reason = health.reason
        # Persisted runs contribute activity only after physical availability.
        if state.active_work and activity != 'WAITING_INPUT':
            activity = 'BUSY'
        row = agent_snapshot.from_physical(agent, state, activity=activity,
            reason=reason, checked_at=checked_at)
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
        elif phase == 'ERROR':
            row.runtime_state = agent_snapshot.RuntimeState.ERROR
            row.activity_state = agent_snapshot.ActivityState.IDLE
            row.reason = operation.get('reason') or 'lifecycle_failed'
        elif operation.get('desired') == 'OFFLINE' and not state.offline:
            row.runtime_state = agent_snapshot.RuntimeState.ERROR
            row.activity_state = agent_snapshot.ActivityState.IDLE
            row.reason = 'unexpected_runtime_after_stop'
        return row
    except Exception as error:
        return agent_snapshot.AgentSnapshot(agent=agent, runtime_state='ERROR',
            activity_state='IDLE', checked_at=checked_at,
            reason=type(error).__name__, persistent=session is not None)


def collect_snapshot(db, allow_restart=False):
    rows = [collect_agent(agent, session, db, allow_restart and agent in ALWAYS_ON_AGENTS)
        for agent, (session, _command) in AGENTS.items()]
    rows.extend(collect_agent(runtime.id, None, db) for runtime in agent_runtimes.RUNTIMES)
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
        with urllib.request.urlopen(request, timeout=8):
            pass
    except OSError:
        run(["logger", "-t", LOG_TAG, "falha ao enviar alerta do supervisor"], timeout=2)


def notify_transitions(previous, health) -> None:
    for item in health:
        old = previous.get(item.agent, {})
        old_status = old.get('runtime_state', old.get('status'))
        current = item.runtime_state.value
        if old_status == current:
            continue
        if current in {'ERROR', 'OFFLINE'}:
            send_alert(f"[agents-healthcheck] {item.agent}: {current} ({item.reason or 'sem processo'}).")
        elif current == 'ONLINE' and old_status in {'ERROR', 'OFFLINE', 'blocked', 'offline'}:
            send_alert(f"[agents-healthcheck] {item.agent}: recuperado, ONLINE.")


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
            health = collect_snapshot(db, allow_restart=not args.no_restart)
        write_state(health)
    notify_transitions(previous, health)
    for item in health:
        print(f"{item.agent}: {item.runtime_state.value}/{item.activity_state.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
