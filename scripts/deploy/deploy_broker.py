#!/usr/bin/env python3
"""CLI privilegiada do broker. Deve rodar somente como workdev-deploy."""

from __future__ import annotations

import argparse
import fcntl
import grp
import json
import os
import subprocess
import sys
from pathlib import Path

from deploy_proof import ProofError, artifact_fingerprint, issue_proof, read_key
from pipeline import (
    DeploymentCallbacks,
    DeploymentPipeline,
    PipelineError,
    atomic_json,
    issue_approval,
)
from post_deploy_gate import run_checks
from release_manager import ReleaseError, ReleaseManager


DEFAULT_STATE = Path("/var/lib/workdev-deploy")
DEFAULT_RUNTIME = Path("/opt/workdev-runtime")
DEFAULT_KEY = Path("/etc/workdev-deploy/signing.key")


def release_manager(runtime: Path) -> ReleaseManager:
    try:
        runtime_gid = grp.getgrnam("workdev-runtime").gr_gid
    except KeyError as error:
        raise PipelineError("grupo workdev-runtime ausente") from error
    if runtime_gid not in os.getgroups():
        raise PipelineError("workdev-deploy nao pertence a workdev-runtime")
    return ReleaseManager(runtime, runtime_gid=runtime_gid)


def require_broker_user(expected: str = "workdev-deploy") -> None:
    import pwd

    if os.environ.get("WORKDEV_DEPLOY_TESTING") == "1":
        return
    if pwd.getpwuid(os.geteuid()).pw_name != expected:
        raise PipelineError(f"broker deve executar como {expected}")


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def privileged(command: list[str]) -> None:
    """Executa somente comandos enumerados na policy de workdev-deploy."""
    run(["sudo", "-n", *command])


def post_deploy_command(command: list[str]):
    if command and command[0] == "ss":
        command = ["sudo", "-n", "/usr/local/libexec/workdev-deploy-readcheck", "port"]
    elif command and command[0] == "journalctl":
        command = ["sudo", "-n", "/usr/local/libexec/workdev-deploy-readcheck", "journal"]
    from post_deploy_gate import system_command

    return system_command(command)


def state_paths(state: Path, proof_id: str) -> tuple[Path, Path, Path]:
    return (
        state / "proofs" / f"{proof_id}.json",
        state / "approvals" / f"{proof_id}.json",
        state / "releases" / f"{proof_id}.json",
    )


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare(args, key: bytes) -> str:
    gate = Path(__file__).resolve().parent / "verificar-deploy.sh"
    environment = {**os.environ, "WORKDEV_DEPLOY_LIB": str(gate.parent)}
    subprocess.run(
        ["timeout", "240", "bash", str(gate), "--testes"],
        check=True,
        env=environment,
    )
    proof = issue_proof(args.root, args.artifact, args.project, key, args.ttl)
    proof_id = proof["proof_id"]
    manager = release_manager(args.runtime)
    release = manager.prepare(args.root, args.artifact, proof_id)
    if artifact_fingerprint(release / "apps/web/dist") != proof["artifact_fingerprint"]:
        raise ReleaseError("artefato da release diverge da prova")
    proof_path, _, release_path = state_paths(args.state, proof_id)
    atomic_json(proof_path, proof)
    atomic_json(release_path, {"proof_id": proof_id, "release": str(release)})
    return proof_id


def approve(args, key: bytes) -> str:
    proof_path, approval_path, _ = state_paths(args.state, args.proof_id)
    proof = load(proof_path)
    approval = issue_approval(proof, args.actor, key)
    atomic_json(approval_path, approval)
    return approval["approval_id"]


def deploy(args, key: bytes) -> str:
    proof_path, approval_path, release_record = state_paths(args.state, args.proof_id)
    proof, approval, release_data = load(proof_path), load(approval_path), load(release_record)
    release = Path(release_data["release"])
    manager = release_manager(args.runtime)
    if artifact_fingerprint(release / "apps/web/dist") != proof.get("artifact_fingerprint"):
        raise PipelineError("artefato preparado diverge da prova")

    def rollback_and_restart() -> None:
        manager.rollback()
        privileged(["systemctl", "restart", "workdev-api.service"])

    callbacks = DeploymentCallbacks(
        promote=lambda: manager.promote(release),
        restart=lambda: privileged(["systemctl", "restart", "workdev-api.service"]),
        postcheck=lambda: run_checks(command=post_deploy_command),
        rollback=rollback_and_restart,
    )
    lock_path = args.state / "deploy.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PipelineError("outro deploy esta em andamento") from error
        pipeline = DeploymentPipeline(args.state, key)
        return pipeline.deploy(
            proof, approval, args.root, args.artifact, args.project, callbacks
        )


def parser():
    result = argparse.ArgumentParser()
    result.add_argument("--state", type=Path, default=DEFAULT_STATE)
    result.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    result.add_argument("--key-file", type=Path, default=DEFAULT_KEY)
    result.add_argument("--root", type=Path, default=Path("/opt/workdev"))
    result.add_argument("--artifact", type=Path, default=Path("/opt/workdev/apps/web/dist"))
    result.add_argument("--project", default="workdev")
    sub = result.add_subparsers(dest="command", required=True)
    prepare_cmd = sub.add_parser("prepare")
    prepare_cmd.add_argument("--ttl", type=int, default=900)
    approve_cmd = sub.add_parser("approve")
    approve_cmd.add_argument("proof_id")
    approve_cmd.add_argument("--actor", required=True)
    deploy_cmd = sub.add_parser("deploy")
    deploy_cmd.add_argument("proof_id")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        require_broker_user()
        key = read_key(args.key_file)
        if args.command == "prepare":
            print(prepare(args, key))
        elif args.command == "approve":
            print(approve(args, key))
        else:
            status = deploy(args, key)
            print(status)
            if status != "DEPLOY_SUCCEEDED":
                return 1
        return 0
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        ProofError,
        PipelineError,
        ReleaseError,
    ) as error:
        print(f"BLOQUEIA: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
