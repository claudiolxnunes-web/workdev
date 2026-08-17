#!/usr/bin/env python3
"""Nucleo fail-closed do pipeline privilegiado de deploy."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
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
            return "DEPLOY_FAILED"

        result = callbacks.postcheck()
        status = str(result.get("status", "DEPLOY_FAILED"))
        if status not in {"DEPLOY_SUCCEEDED", "DEPLOY_DEGRADED", "DEPLOY_FAILED"}:
            status = "DEPLOY_FAILED"
        self._record(run_id, status, post_deploy=result)
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
        return status
