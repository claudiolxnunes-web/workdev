from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from pathlib import Path

import pytest

from app.models.handoff import AgentBuildJob, AgentRun
from app.services import agent_reset


class Query:
    def __init__(self, db, model):
        self.db, self.model = db, model

    def filter(self, *args): return self
    def join(self, *args): return self
    def order_by(self, *args): return self
    def with_for_update(self, *args, **kwargs): return self

    def all(self):
        if self.model is AgentRun:
            return [row for row in self.db.runs if row.status == "running"]
        if self.model is AgentBuildJob:
            return [row for row in self.db.jobs if row.state in agent_reset.ACTIVE_JOB_STATES]
        return []


class FakeDb:
    def __init__(self):
        now = datetime.now(timezone.utc)
        run_id = uuid4()
        self.runs = [SimpleNamespace(id=run_id, agent="codex", status="running", created_at=now,
            summary=None, error=None, finished_at=None, updated_at=now, dispatch_state="dispatching")]
        self.jobs = [SimpleNamespace(id=uuid4(), run_id=run_id, runtime_id="codex", state="running",
            created_at=now, error=None, finished_at=None, payload={})]
        self.events = []
        self.commits = 0

    def query(self, model): return Query(self, model)
    def add(self, row): self.events.append(row)
    def commit(self): self.commits += 1
    def rollback(self): pass


@pytest.fixture
def reset_world(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKDEV_SESSION_SECRET", "reset-test-secret")
    monkeypatch.setattr(agent_reset, "LOCK_FILE", tmp_path / "reset.lock")
    monkeypatch.setattr(agent_reset.agent_snapshot, "file_lock", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(agent_reset.agent_lifecycle, "agent_lock", lambda *args, **kwargs: nullcontext())
    groups = tmp_path / "groups.json"
    monkeypatch.setattr(agent_reset.agent_lifecycle, "GROUPS_FILE", groups)
    lifecycle = tmp_path / "lifecycle"
    lifecycle.mkdir()
    (lifecycle / "codex.json").write_text('{"phase":"ERROR"}')
    sessions = {"codex", "auto-codex-run-id"}

    def tmux(command):
        if command[0] == "list-sessions":
            output = "".join(f"{name}\t1\n" for name in sorted(sessions))
            return SimpleNamespace(returncode=0 if sessions else 1, stdout=output,
                stderr="" if sessions else "no server running")
        sessions.discard(command[-1].removeprefix("="))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(agent_reset, "_tmux", tmux)
    return FakeDb(), sessions, lifecycle


def test_preview_is_read_only_and_lists_all_layers(reset_world):
    db, sessions, lifecycle = reset_world
    result = agent_reset.preview(db)
    assert {row["name"] for row in result["sessions"]} == sessions
    assert result["sessions"][0]["auto"] is True
    assert result["lifecycle_files"] == [{"agent": "codex", "path": str(lifecycle / "codex.json"), "phase": "ERROR"}]
    assert len(result["runs"]) == len(result["jobs"]) == 1
    assert db.commits == 0 and (lifecycle / "codex.json").exists()


def test_execute_cancels_without_restart_and_is_idempotent(reset_world):
    db, sessions, lifecycle = reset_world
    result = agent_reset.execute(db, agent_reset.preview(db)["confirmation_token"])
    assert sessions == set() and not (lifecycle / "codex.json").exists()
    assert db.runs[0].status == "cancelled" and db.runs[0].finished_at
    assert db.jobs[0].state == "cancelled" and db.jobs[0].finished_at
    assert result["agents_restarted"] == []
    assert any(event.event_type == "workspace.agent_reset" and event.run_id is None for event in db.events)
    second = agent_reset.execute(db, agent_reset.preview(db)["confirmation_token"])
    assert second["sessions_killed"] == second["runs_cancelled"] == second["jobs_cancelled"] == []


def test_execute_rejects_changed_impact(reset_world):
    db, sessions, _ = reset_world
    token = agent_reset.preview(db)["confirmation_token"]
    sessions.add("qwen")
    with pytest.raises(agent_reset.ResetConflict, match="impacto mudou"):
        agent_reset.execute(db, token)


def test_incremental_real_tmux_disposable(tmp_path, monkeypatch):
    socket_root = tmp_path / "tmux"
    socket_root.mkdir(mode=0o700)
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("TMUX_TMPDIR", str(socket_root))
    monkeypatch.setenv("WORKDEV_SESSION_SECRET", "reset-real-tmux-test")
    monkeypatch.setattr(agent_reset, "LOCK_FILE", tmp_path / "reset.lock")
    groups = tmp_path / "state" / "groups.json"
    groups.parent.mkdir()
    monkeypatch.setattr(agent_reset.agent_lifecycle, "GROUPS_FILE", groups)
    result = subprocess.run(["tmux", "new-session", "-d", "-s", "reset-disposable", "sleep 30"],
                            env=os.environ.copy(), capture_output=True, text=True, check=False)
    if result.returncode != 0 and "Operation not permitted" in result.stderr:
        pytest.skip("sandbox não permite criar socket tmux; executar este teste fora dele")
    assert result.returncode == 0, result.stderr
    try:
        db = FakeDb()
        impact = agent_reset.preview(db)
        assert [row["name"] for row in impact["sessions"]] == ["reset-disposable"]
        outcome = agent_reset.execute(db, impact["confirmation_token"])
        assert outcome["sessions_killed"] == ["reset-disposable"]
        assert agent_reset._sessions() == []
    finally:
        subprocess.run(["tmux", "kill-server"], env=os.environ.copy(),
                       capture_output=True, check=False)


def test_readonly_credential_cannot_preview_or_execute(monkeypatch):
    from starlette.requests import Request
    from app.auth import request_is_authenticated
    readonly = "readonly-reset-test-" + "a" * 32
    monkeypatch.setenv("WORKDEV_READONLY_API_KEY", readonly)
    def request(method, path):
        return Request({"type": "http", "method": method, "path": path,
            "headers": [(b"x-api-key", readonly.encode())], "query_string": b"",
            "server": ("test", 80), "scheme": "http"})
    assert request_is_authenticated(request("GET", "/api/agents/reset/preview")) is False
    assert request_is_authenticated(request("POST", "/api/agents/reset")) is False


def test_manual_script_preview_and_execute_through_local_api(tmp_path):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def _reply(self, payload):
            body = __import__("json").dumps(payload).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self):
            requests.append(("GET", self.path, self.headers.get("X-API-Key"), None))
            self._reply({"sessions": [], "confirmation_token": "preview-token"})
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
            requests.append(("POST", self.path, self.headers.get("X-API-Key"), body))
            self._reply({"status": "reset"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    script = str(Path(__file__).resolve().parents[3] / "scripts/workdev-reset-agents.sh")
    env = {**os.environ, "WORKDEV_LOCAL_API": f"http://127.0.0.1:{server.server_port}/api",
           "WORKDEV_API_KEY": "manual-test-key"}
    env.pop("DATABASE_URL", None)
    try:
        preview_call = subprocess.run([script, "preview"], env=env, capture_output=True, text=True, check=False)
        execute_call = subprocess.run([script, "execute", "--confirmation-token", "preview-token"],
                                      env=env, capture_output=True, text=True, check=False)
    finally:
        server.shutdown(); thread.join(timeout=2); server.server_close()
    assert preview_call.returncode == execute_call.returncode == 0
    assert requests == [
        ("GET", "/api/agents/reset/preview", "manual-test-key", None),
        ("POST", "/api/agents/reset", "manual-test-key", '{"confirmation_token":"preview-token"}'),
    ]
