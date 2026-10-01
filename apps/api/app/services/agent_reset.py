"""Reset manual, confirmado e auditado das execucoes locais de agentes."""
from __future__ import annotations

import argparse
import base64
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.handoff import AgentBuildJob, AgentRun, AgentRunEvent
from app.services import agent_lifecycle, agent_snapshot


RESET_REASON = "abortado por reset manual de sessões"
ACTIVE_JOB_STATES = ("queued", "running")
TOKEN_TTL_SECONDS = 300
LOCAL_AGENTS = ("claude", "codex", "gemini", "kimi", "local-code", "openrouter")
LOCK_FILE = Path(os.getenv("WORKDEV_AGENT_RESET_LOCK", "/opt/workdev/.workdev/locks/agent-reset.lock"))


class ResetConflict(RuntimeError):
    pass


def _tmux(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["tmux", *command], capture_output=True, text=True, timeout=10, check=False)


def _sessions() -> list[dict]:
    result = _tmux(["list-sessions", "-F", "#{session_name}\t#{session_created}"])
    if result.returncode != 0:
        # tmux usa exit 1 quando nao existe servidor/sessao: estado vazio e idempotente.
        if "no server running" in result.stderr or "no sessions" in result.stderr or not result.stderr.strip():
            return []
        raise RuntimeError(result.stderr.strip() or "falha ao listar sessões tmux")
    rows = []
    for line in result.stdout.splitlines():
        name, _, created = line.partition("\t")
        if name:
            rows.append({"name": name, "created_at": int(created) if created.isdigit() else None,
                         "auto": name.startswith("auto-")})
    return sorted(rows, key=lambda row: row["name"])


def _lifecycle_files() -> list[dict]:
    directory = agent_lifecycle.GROUPS_FILE.parent / "lifecycle"
    rows = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
            phase = payload.get("phase") if isinstance(payload, dict) else "invalid"
        except (OSError, ValueError, TypeError):
            phase = "unreadable"
        rows.append({"agent": path.stem, "path": str(path), "phase": phase})
    return rows


def _impact(db: Session) -> dict:
    runs = (db.query(AgentRun).filter(AgentRun.status == "running", AgentRun.agent.in_(LOCAL_AGENTS))
            .order_by(AgentRun.created_at, AgentRun.id).all())
    jobs = (db.query(AgentBuildJob).join(AgentRun, AgentRun.id == AgentBuildJob.run_id)
            .filter(AgentBuildJob.state.in_(ACTIVE_JOB_STATES), AgentRun.agent.in_(LOCAL_AGENTS))
            .order_by(AgentBuildJob.created_at, AgentBuildJob.id).all())
    return {
        "sessions": _sessions(),
        "lifecycle_files": _lifecycle_files(),
        "runs": [{"id": str(row.id), "agent": row.agent, "status": row.status} for row in runs],
        "jobs": [{"id": str(row.id), "run_id": str(row.run_id), "runtime_id": row.runtime_id,
                  "state": row.state} for row in jobs],
    }


def _fingerprint(impact: dict) -> str:
    raw = json.dumps(impact, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _secret() -> bytes:
    value = os.getenv("WORKDEV_SESSION_SECRET") or os.getenv("WORKDEV_API_KEY")
    if not value:
        raise RuntimeError("WORKDEV_SESSION_SECRET não configurada")
    return value.encode()


def _token(impact: dict, issued_at: int | None = None) -> str:
    payload = f"{issued_at or int(time.time())}:{_fingerprint(impact)}"
    signature = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode().rstrip("=")


def preview(db: Session) -> dict:
    impact = _impact(db)
    return {**impact, "reason": RESET_REASON, "confirmation_token": _token(impact),
            "token_ttl_seconds": TOKEN_TTL_SECONDS}


def _validate_token(token: str, impact: dict) -> None:
    try:
        padded = token + "=" * (-len(token) % 4)
        issued, fingerprint, signature = base64.urlsafe_b64decode(padded).decode().split(":", 2)
        payload = f"{issued}:{fingerprint}"
        valid = hmac.compare_digest(signature, hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest())
        fresh = 0 <= int(time.time()) - int(issued) <= TOKEN_TTL_SECONDS
    except (ValueError, TypeError, UnicodeDecodeError):
        valid = fresh = False
        fingerprint = ""
    if not valid or not fresh:
        raise ResetConflict("confirmação inválida ou expirada; gere um novo preview")
    if not hmac.compare_digest(fingerprint, _fingerprint(impact)):
        raise ResetConflict("o impacto mudou desde o preview; revise a nova lista antes de confirmar")


def execute(db: Session, confirmation_token: str) -> dict:
    with agent_snapshot.file_lock(LOCK_FILE), ExitStack() as locks:
        for agent in LOCAL_AGENTS:
            locks.enter_context(agent_lifecycle.agent_lock(agent))
        impact = _impact(db)
        _validate_token(confirmation_token, impact)

        # As linhas ficam travadas antes do primeiro efeito fisico. Assim um
        # worker nao consegue concluir/cancelar a mesma execucao entre o kill
        # e a persistencia terminal deste reset.
        runs = (db.query(AgentRun).filter(AgentRun.status == "running",
                AgentRun.agent.in_(LOCAL_AGENTS)).with_for_update().all())
        jobs = (db.query(AgentBuildJob).join(AgentRun, AgentRun.id == AgentBuildJob.run_id)
                .filter(AgentBuildJob.state.in_(ACTIVE_JOB_STATES),
                        AgentRun.agent.in_(LOCAL_AGENTS)).with_for_update().all())
        run_ids = {row["id"] for row in impact["runs"]}
        job_ids = {row["id"] for row in impact["jobs"]}
        if {str(row.id) for row in runs} != run_ids or {str(row.id) for row in jobs} != job_ids:
            db.rollback()
            raise ResetConflict("o banco mudou durante o reset; gere um novo preview")

        killed = []
        for row in impact["sessions"]:
            result = _tmux(["kill-session", "-t", f"={row['name']}"])
            if result.returncode != 0 and "can't find session" not in result.stderr:
                raise RuntimeError(result.stderr.strip() or f"falha ao encerrar {row['name']}")
            killed.append(row["name"])
        survivors = _sessions()
        if survivors:
            raise RuntimeError("sessões tmux sobreviveram ao reset: " + ", ".join(row["name"] for row in survivors))

        removed = []
        for row in impact["lifecycle_files"]:
            path = Path(row["path"])
            path.unlink(missing_ok=True)
            removed.append(str(path))

        now = datetime.now(timezone.utc)
        for job in jobs:
            job.state = "cancelled"
            job.error = RESET_REASON
            job.finished_at = now
            job.payload = {**(job.payload or {}), "reset_reason": RESET_REASON,
                           "reset_at": now.isoformat()}
        for run in runs:
            previous = run.status
            run.status = "cancelled"
            run.summary = RESET_REASON
            run.error = RESET_REASON
            run.finished_at = now
            run.updated_at = now
            run.dispatch_state = "failed"
            db.add(AgentRunEvent(run_id=run.id, event_type="build.cancelled", message=RESET_REASON,
                                 payload={"from": previous, "to": "cancelled", "source": "manual_agent_reset"}))
        db.add(AgentRunEvent(run_id=None, event_type="workspace.agent_reset", message=RESET_REASON,
                             payload={"sessions": killed, "lifecycle_files": removed,
                                      "runs_cancelled": sorted(run_ids),
                                      "jobs_cancelled": sorted(job_ids),
                                      "actor": "authenticated_operator"}))
        db.commit()
        return {"status": "reset", "reason": RESET_REASON, "reset_at": now.isoformat(),
                "sessions_killed": killed, "lifecycle_files_removed": removed,
                "runs_cancelled": sorted(run_ids), "jobs_cancelled": sorted(job_ids),
                "agents_restarted": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview/reset confirmado de todas as sessões de agentes")
    parser.add_argument("action", choices=("preview", "execute"))
    parser.add_argument("--confirmation-token")
    args = parser.parse_args()
    if args.action == "execute" and not args.confirmation_token:
        parser.error("execute exige --confirmation-token retornado pelo preview")
    if args.action == "execute" and os.getenv("TMUX"):
        parser.error("execute deve rodar fora do tmux que será encerrado; use SSH/console ou a API")
    with SessionLocal() as db:
        try:
            result = preview(db) if args.action == "preview" else execute(db, args.confirmation_token)
        except ResetConflict as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
