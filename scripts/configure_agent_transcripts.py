#!/usr/bin/env python3
"""Configura captura append-only nas sessões existentes sem reiniciá-las."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(os.getenv("WORKDEV_DIR", "/opt/workdev"))
TRANSCRIPT_DIR = Path(
    os.getenv("AGENT_TRANSCRIPT_DIR", "/var/lib/workdev/agent-transcripts")
)
SESSIONS = {
    "claude": "code",
    "codex": "codex",
    "gemini": "gemini",
    "kimi": "kimi",
    "qwen": "qwen",
}


def run(*command: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, capture_output=True, timeout=10, check=False)


def configure(agent: str, session: str) -> bool:
    target = f"={session}:"
    if run("tmux", "has-session", "-t", f"={session}").returncode != 0:
        return False
    TRANSCRIPT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    TRANSCRIPT_DIR.chmod(0o700)
    path = TRANSCRIPT_DIR / f"{agent}.ansi.log"
    if not path.exists() or path.stat().st_size == 0:
        snapshot = run("tmux", "capture-pane", "-p", "-J", "-S", "-100000", "-t", target)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "ab", closefd=True) as handle:
            handle.write(snapshot.stdout)
            if snapshot.stdout and not snapshot.stdout.endswith(b"\n"):
                handle.write(b"\n")
    sink = ROOT / "scripts" / "agent_transcript_sink.py"
    command = f"exec {sink} {agent}"
    result = run("tmux", "pipe-pane", "-o", "-t", target, command)
    return result.returncode == 0


def main() -> int:
    failed = [agent for agent, session in SESSIONS.items() if not configure(agent, session)]
    if failed:
        print("Falha ao configurar transcript: " + ", ".join(failed))
        return 1
    print("Transcripts configurados: " + ", ".join(SESSIONS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
