#!/usr/bin/env python3
"""Nucleo fail-closed do pipeline privilegiado de deploy."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from deploy_proof import ProofError, canonical, sign, verify_proof


class PipelineError(RuntimeError):
    pass


def atomic_json(path: Path, payload: dict[str, Any], mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        if temporary.exists():
            temporary.unlink()


def proof_digest(proof: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical(proof)).hexdigest()


def issue_approval(
    proof: dict[str, Any], actor: str, key: bytes, now: int | None = None
) -> dict[str, Any]:
    if proof.get("result") != "PASS" or not proof.get("proof_id"):
        raise PipelineError("somente prova PASS pode ser aprovada")
    current = int(time.time() if now is None else now)
    if current > int(proof.get("expires_at", 0)):
        raise PipelineError("prova expirada nao pode ser aprovada")
    approval = {
        "schema": 1,
        "approval_id": hashlib.sha256(
            f"{proof['proof_id']}:{actor}:{current}".encode()
        ).hexdigest()[:32],
        "proof_id": proof["proof_id"],
        "proof_digest": proof_digest(proof),
        "project": proof.get("project"),
        "actor": actor,
        "approved_at": current,
        "expires_at": proof["expires_at"],
        "decision": "APPROVED",
    }
    approval["signature"] = sign(approval, key)
    return approval


def verify_approval(
    approval: dict[str, Any], proof: dict[str, Any], key: bytes, now: int | None = None
) -> None:
    if not hmac.compare_digest(str(approval.get("signature", "")), sign(approval, key)):
        raise PipelineError("assinatura da aprovacao invalida")
    if approval.get("decision") != "APPROVED":
        raise PipelineError("deploy nao aprovado")
    if approval.get("proof_id") != proof.get("proof_id"):
        raise PipelineError("aprovacao pertence a outra prova")
    if approval.get("proof_digest") != proof_digest(proof):
        raise PipelineError("prova mudou depois da aprovacao")
    current = int(time.time() if now is None else now)
    if current > int(approval.get("expires_at", 0)):
        raise PipelineError("aprovacao expirada")


class ProofConsumer:
    def __init__(self, state_dir: Path):
        self.consumed_dir = state_dir / "consumed"

    def consume(self, proof: dict[str, Any], approval: dict[str, Any], now: int) -> Path:
        self.consumed_dir.mkdir(parents=True, exist_ok=True)
        path = self.consumed_dir / f"{proof['proof_id']}.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {
                    "proof_id": proof["proof_id"],
                    "approval_id": approval["approval_id"],
                    "consumed_at": now,
                },
                stream,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        return path


@dataclass
class DeploymentCallbacks:
    promote: Callable[[], None]
    restart: Callable[[], None]
    postcheck: Callable[[], dict[str, Any]]
    rollback: Callable[[], None]


def _persist_deployment_outcome(
    proof: dict[str, Any],
    outcome: str,
    postcheck_result: dict[str, Any] | None = None,
    error_message: str | None = None,
    api_url: str = "http://127.0.0.1:8000",
    api_key: str | None = None,
) -> None:
    """
    Persistir o resultado do deploy no banco de dados via API.

    `outcome` deve ser um valor do enum deployment_outcome
    (success, rolled_back, hotfixed, degraded). Mapeamento dos status
    do pipeline, sem inventar estados novos:
    - DEPLOY_SUCCEEDED -> success
    - DEPLOY_DEGRADED -> degraded
    - DEPLOY_FAILED com rollback bem-sucedido -> rolled_back
    - DEPLOY_FAILED com rollback falho -> rolled_back, com
      error_message prefixado por "rollback_failed:" para distinguir
      os dois cenarios (o enum nao possui estado proprio para isso).

    O artifact_fingerprint da prova vem no formato "sha256:<64 hex>";
    o schema da API aceita no maximo 64 caracteres, entao o prefixo e
    removido antes do envio (causa raiz do HTTP 422 original).
    """
    proof_id = str(proof.get("proof_id", ""))
    project = str(proof.get("project", "workdev-core"))
    artifact_fingerprint = str(
        proof.get("artifact_fingerprint", "")
    ).removeprefix("sha256:")

    payload = {
        "proof_id": proof_id,
        "project": project,
        "artifact_fingerprint": artifact_fingerprint,
        "outcome": outcome,
        "commit_sha": proof.get("commit_sha"),
        "deployment_url": None,
        "postcheck_result": postcheck_result,
        "error_message": error_message,
    }

    if not api_key:
        key_file = Path("/etc/workdev-deploy/api.key")
        try:
            if key_file.is_file():
                api_key = key_file.read_text(encoding="utf-8").strip()
        except OSError:
            api_key = None

    try:
        req = urllib.request.Request(
            f"{api_url}/api/deployments/outcomes",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-API-Key": api_key or "",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            response.read()
    except Exception as e:
        # Falha ao persistir não deve falhar o deploy, apenas logar
        print(f"Warning: failed to persist deployment outcome: {e}", file=sys.stderr)


class DeploymentPipeline:
    def __init__(self, state_dir: Path, key: bytes):
        self.state_dir = state_dir
        self.key = key
        self.consumer = ProofConsumer(state_dir)

    def _record(self, run_id: str, status: str, **details: Any) -> None:
        atomic_json(
            self.state_dir / "runs" / f"{run_id}.json",
            {"run_id": run_id, "status": status, **details},
        )

    def deploy(
        self,
        proof: dict[str, Any],
        approval: dict[str, Any],
        root: Path,
        artifact_dir: Path,
        project: str,
        callbacks: DeploymentCallbacks,
        now: int | None = None,
    ) -> str:
        current = int(time.time() if now is None else now)
        run_id = str(proof.get("proof_id", "invalid"))
        try:
            verify_proof(proof, root, artifact_dir, project, self.key, current)
            verify_approval(approval, proof, self.key, current)
            self.consumer.consume(proof, approval, current)
        except (ProofError, PipelineError, FileExistsError, OSError) as error:
            self._record(run_id, "DEPLOY_REJECTED", error=str(error))
            raise PipelineError(str(error)) from error

        self._record(run_id, "DEPLOYING", started_at=current)
        try:
            callbacks.promote()
            callbacks.restart()
        except Exception as error:
            self._record(run_id, "DEPLOY_FAILED", error=str(error))
            error_message = f"deploy_failed: {error}"
            try:
                callbacks.rollback()
                self._record(run_id, "ROLLED_BACK", error=str(error))
            except Exception as rollback_error:
                self._record(
                    run_id,
                    "ROLLBACK_FAILED",
                    error=str(error),
                    rollback_error=str(rollback_error),
                )
                error_message = f"rollback_failed: {rollback_error}; {error_message}"
            # Persistir falha de promote/restart: sem esta chamada o outcome
            # nunca chegava ao banco e o Change Failure Rate ficava sub-contado.
            _persist_deployment_outcome(
                proof, "rolled_back", error_message=error_message
            )
            return "DEPLOY_FAILED"

        result = callbacks.postcheck()
        status = str(result.get("status", "DEPLOY_FAILED"))
        if status not in {"DEPLOY_SUCCEEDED", "DEPLOY_DEGRADED", "DEPLOY_FAILED"}:
            status = "DEPLOY_FAILED"
        self._record(run_id, status, post_deploy=result)

        error_message = None
        if status == "DEPLOY_FAILED":
            try:
                callbacks.rollback()
                self._record(run_id, "ROLLED_BACK", post_deploy=result)
            except Exception as rollback_error:
                self._record(
                    run_id,
                    "ROLLBACK_FAILED",
                    post_deploy=result,
                    rollback_error=str(rollback_error),
                )
                error_message = f"rollback_failed: {rollback_error}"
            outcome = "rolled_back"
        else:
            outcome = "success" if status == "DEPLOY_SUCCEEDED" else "degraded"

        # Persistir o deployment outcome no banco de dados, depois do
        # rollback, para que o outcome reflita o estado final real.
        _persist_deployment_outcome(
            proof, outcome, postcheck_result=result, error_message=error_message
        )
        return status
