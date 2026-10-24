import importlib.util
import os
import sys
from pathlib import Path

from app.services import terminal_transcript


SCRIPT = Path(__file__).parents[3] / "scripts" / "agent_transcript_sink.py"
SPEC = importlib.util.spec_from_file_location("agent_transcript_sink", SCRIPT)
sink = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = sink
SPEC.loader.exec_module(sink)


def test_cleans_ansi_osc_backspace_and_carriage_return():
    payload = b"\x1b[32mverde\x1b[0m\r\nabc\bX\x1b]0;titulo\x07\n"
    assert terminal_transcript.clean_terminal_text(payload) == "verde\nabX"


def test_reads_only_tail_without_partial_first_line(tmp_path, monkeypatch):
    monkeypatch.setattr(terminal_transcript, "TRANSCRIPT_DIR", tmp_path)
    path = tmp_path / "codex.ansi.log"
    path.write_text("primeira\nsegunda\nterceira\n", encoding="utf-8")
    content, updated_at = terminal_transcript.read_transcript("codex", max_bytes=17)
    assert content == "terceira"
    assert updated_at is not None


def test_sink_rotates_private_transcript(tmp_path, monkeypatch):
    path = tmp_path / "codex.ansi.log"
    path.write_bytes(b"old")
    path.chmod(0o600)
    sink.rotate(path)
    assert not path.exists()
    assert (tmp_path / "codex.ansi.log.1").read_bytes() == b"old"
