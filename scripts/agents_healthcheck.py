#!/usr/bin/env python3
"""Supervisiona as sessões tmux dos agentes sem expor credenciais."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


WORKDEV_DIR = Path(os.environ.get("WORKDEV_DIR", "/opt/workdev"))
STATE_FILE = Path(os.environ.get("AGENTS_HEALTH_STATE", "/var/lib/agents-healthcheck/status.json"))
ALERT_ENV = Path(os.environ.get("AGENTS_ALERT_ENV", "/opt/scripts/alerta.env"))
LOG_TAG = "agents-healthcheck"

AGENTS = {
    "claude": ("code", [str(WORKDEV_DIR / "scripts/start_claude_agent.sh")]),
    "codex": ("codex", [str(WORKDEV_DIR / "scripts/start_codex_agent.sh")]),
    "kimi": ("kimi",["env", "KIMI_PROVIDER=openrouter", str(WORKDEV_DIR / "scripts/start_kimi_agent.sh")],
    ),
    "qwen": ("qwen", [str(WORKDEV_DIR / "scripts/start_qwen_agent.sh")]),
    "gemini": ("gemini", [str(WORKDEV_DIR / "scripts/start_gemini_agent.sh")]),
}

SHELL_PROCESSES = {"bash", "dash", "fish", "sh", "tmux", "zsh"}
BLOCKED_PATTERNS = (
    (re.compile(r"\b401\b|auth(?:entication)?[_ ]error|missing authentication", re.I), "authentication"),
    (re.compile(r"\b429\b|insufficient balance|recharge your account|billing", re.I), "billing"),
    (re.compile(r"api key.*(?:missing|invalid)|(?:missing|invalid).*api key", re.I), "api_key"),
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


def session_exists(session: str) -> bool:
    return run(["tmux", "has-session", "-t", session], timeout=2).returncode == 0


def current_process(session: str) -> str:
    result = run(
        ["tmux", "display-message", "-p", "-t", session, "#{pane_current_command}"],
        timeout=2,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def capture_recent(session: str, lines: int = 40) -> str:
    result = run(["tmux", "capture-pane", "-p", "-J", "-S", f"-{lines}", "-t", session])
    return result.stdout if result.returncode == 0 else ""


def classify(agent: str, session: str, process: str, output: str, checked_at: str) -> AgentHealth:
    if not process or process in SHELL_PROCESSES:
        return AgentHealth(agent, session, "offline", process, "agent_process_missing", checked_at)
    recent = "\n".join(output.splitlines()[-25:])
    for pattern, reason in BLOCKED_PATTERNS:
        if pattern.search(recent):
            return AgentHealth(agent, session, "blocked", process, reason, checked_at)
    if any(pattern.search(recent) for pattern in BUSY_PATTERNS):
        return AgentHealth(agent, session, "busy", process, None, checked_at)
    return AgentHealth(agent, session, "idle", process, None, checked_at)


def start_session(session: str, command: Sequence[str]) -> bool:
    result = run(
        ["tmux", "new-session", "-d", "-s", session, "-c", str(WORKDEV_DIR), *command],
        timeout=10,
    )
    return result.returncode == 0


def inspect_agent(agent: str, allow_restart: bool = True) -> AgentHealth:
    session, command = AGENTS[agent]
    checked_at = datetime.now(timezone.utc).isoformat()
    exists = session_exists(session)
    process = current_process(session) if exists else ""
    output = capture_recent(session) if exists else ""
    health = classify(agent, session, process, output, checked_at)
    if health.status != "offline" or not allow_restart:
        return health

    if exists:
        run(["tmux", "kill-session", "-t", session], timeout=3)
    if not start_session(session, command):
        return health
    process = current_process(session)
    recovered = classify(agent, session, process, capture_recent(session), checked_at)
    recovered.recovered = recovered.status != "offline"
    return recovered


def write_state(health: list[AgentHealth]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "agents": {item.agent: asdict(item) for item in health},
    }
    with tempfile.NamedTemporaryFile("w", dir=STATE_FILE.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.chmod(0o644)
    temporary.replace(STATE_FILE)


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


def notify_transitions(previous: dict[str, dict], health: list[AgentHealth]) -> None:
    for item in health:
        old_status = previous.get(item.agent, {}).get("status")
        if old_status == item.status:
            continue
        if item.status in {"blocked", "offline"}:
            detail = f" ({item.reason})" if item.reason else ""
            send_alert(f"[agents-healthcheck] {item.agent}: {item.status}{detail}.")
        elif old_status in {"blocked", "offline"}:
            send_alert(f"[agents-healthcheck] {item.agent}: recuperado, estado {item.status}.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="executa uma única verificação")
    parser.add_argument("--no-restart", action="store_true", help="não recupera sessões offline")
    args = parser.parse_args()
    previous = read_previous_state()
    always_on = set()
    health = [
        inspect_agent(
            agent,
            allow_restart=(not args.no_restart and agent in always_on),
        )
        for agent in AGENTS
    ]
    write_state(health)
    notify_transitions(previous, health)
    for item in health:
        print(f"{item.agent}: {item.status} ({item.process or 'sem processo'})")
    return 1 if any(item.agent in always_on and item.status == "offline" for item in health) else 0


if __name__ == "__main__":
    raise SystemExit(main())
