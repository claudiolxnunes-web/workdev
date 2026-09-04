#!/usr/bin/env python3
"""Recebe bytes de ``tmux pipe-pane`` e mantém log privado com rotação."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ALLOWED_AGENTS = {"claude", "codex", "gemini", "kimi", "qwen"}
TRANSCRIPT_DIR = Path(
    os.getenv("AGENT_TRANSCRIPT_DIR", "/var/lib/workdev/agent-transcripts")
)
MAX_BYTES = int(os.getenv("AGENT_TRANSCRIPT_MAX_BYTES", str(20 * 1024 * 1024)))


def rotate(path: Path) -> None:
    oldest = path.with_suffix(path.suffix + ".3")
    oldest.unlink(missing_ok=True)
    for number in (2, 1):
        source = path.with_suffix(path.suffix + f".{number}")
        if source.exists():
            source.replace(path.with_suffix(path.suffix + f".{number + 1}"))
    if path.exists():
        path.replace(path.with_suffix(path.suffix + ".1"))


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ALLOWED_AGENTS:
        print("uso: agent_transcript_sink.py <agent>", file=sys.stderr)
        return 2
    TRANSCRIPT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    TRANSCRIPT_DIR.chmod(0o700)
    path = TRANSCRIPT_DIR / f"{sys.argv[1]}.ansi.log"
    while chunk := sys.stdin.buffer.read(65536):
        if path.exists() and path.stat().st_size + len(chunk) > MAX_BYTES:
            rotate(path)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "ab", closefd=True) as handle:
            handle.write(chunk)
            handle.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
