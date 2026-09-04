"""Leitura segura dos transcripts append-only produzidos pelo tmux."""

from __future__ import annotations

import os
import re
from pathlib import Path


TRANSCRIPT_DIR = Path(
    os.getenv("AGENT_TRANSCRIPT_DIR", "/opt/workdev/.local/agent-transcripts")
)

_OSC = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")
_DCS = re.compile(r"\x1bP.*?\x1b\\", re.DOTALL)
_CSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|[@-_])")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_terminal_text(payload: bytes | str) -> str:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    text = _OSC.sub("", text)
    text = _DCS.sub("", text)
    text = _CSI.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    while "\b" in text:
        text = re.sub(r"[^\n]\x08", "", text)
        text = text.replace("\b", "")
    text = _CONTROL.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def transcript_path(agent: str) -> Path:
    return TRANSCRIPT_DIR / f"{agent}.ansi.log"


def read_transcript(agent: str, max_bytes: int = 5_000_000) -> tuple[str, float | None]:
    path = transcript_path(agent)
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
                handle.readline()
            content = handle.read(max_bytes)
        return clean_terminal_text(content), path.stat().st_mtime
    except FileNotFoundError:
        return "", None
