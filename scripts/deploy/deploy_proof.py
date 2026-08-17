#!/usr/bin/env python3
"""Fingerprint e prova assinada para o pipeline de deploy.

Esta etapa apenas cria/verifica provas. Ela nao executa deploy, restart, push ou
qualquer acao destrutiva. A chave deve ficar fora do repositorio e protegida
pelo futuro broker privilegiado.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


class ProofError(RuntimeError):
    pass


def git(root: Path, *args: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    )
    return completed.stdout.decode().strip() if text else completed.stdout


def require_clean_tree(root: Path) -> None:
    status = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise ProofError("arvore de trabalho nao esta limpa")


def source_fingerprint(root: Path) -> dict[str, str]:
    """Hash canonico do commit e do conteudo versionado da arvore limpa."""
    require_clean_tree(root)
    commit = str(git(root, "rev-parse", "HEAD"))
    names_raw = git(root, "ls-files", "-z", text=False)
    assert isinstance(names_raw, bytes)
    names = sorted(name for name in names_raw.split(b"\0") if name)
    digest = hashlib.sha256()
    for encoded_name in names:
        name = encoded_name.decode(errors="surrogateescape")
        path = root / name
        stat = path.lstat()
        digest.update(encoded_name)
        digest.update(b"\0")
        digest.update(oct(stat.st_mode & 0o777).encode())
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(os.readlink(path).encode(errors="surrogateescape"))
        else:
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return {"commit_sha": commit, "source_fingerprint": f"sha256:{digest.hexdigest()}"}


def artifact_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.is_dir():
        raise ProofError(f"diretorio de artefato ausente: {path}")
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        relative = item.relative_to(path).as_posix().encode()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def canonical(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    return json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def sign(payload: dict[str, Any], key: bytes) -> str:
    return "hmac-sha256:" + hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()


def issue_proof(
    root: Path,
    artifact_dir: Path,
    project: str,
    key: bytes,
    ttl_seconds: int = 900,
    now: int | None = None,
) -> dict[str, Any]:
    if ttl_seconds < 1 or ttl_seconds > 3600:
        raise ProofError("validade deve ficar entre 1 e 3600 segundos")
    current = int(time.time() if now is None else now)
    state = source_fingerprint(root)
    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "proof_id": str(uuid.uuid4()),
        "project": project,
        **state,
        "artifact_fingerprint": artifact_fingerprint(artifact_dir),
        "tested_at": current,
        "expires_at": current + ttl_seconds,
        "result": "PASS",
    }
    payload["signature"] = sign(payload, key)
    return payload


def verify_proof(
    proof: dict[str, Any],
    root: Path,
    artifact_dir: Path,
    project: str,
    key: bytes,
    now: int | None = None,
) -> None:
    if proof.get("schema") != SCHEMA_VERSION:
        raise ProofError("schema de prova desconhecido")
    supplied = str(proof.get("signature", ""))
    if not hmac.compare_digest(supplied, sign(proof, key)):
        raise ProofError("assinatura invalida")
    if proof.get("project") != project:
        raise ProofError("prova pertence a outro projeto")
    if proof.get("result") != "PASS":
        raise ProofError("gate nao produziu PASS")
    current = int(time.time() if now is None else now)
    if current > int(proof.get("expires_at", 0)):
        raise ProofError("prova expirada")
    state = source_fingerprint(root)
    if proof.get("commit_sha") != state["commit_sha"]:
        raise ProofError("commit mudou depois da verificacao")
    if proof.get("source_fingerprint") != state["source_fingerprint"]:
        raise ProofError("codigo mudou depois da verificacao")
    if proof.get("artifact_fingerprint") != artifact_fingerprint(artifact_dir):
        raise ProofError("artefato mudou depois da verificacao")


def read_key(path: Path) -> bytes:
    key = path.read_bytes().strip()
    if len(key) < 32:
        raise ProofError("chave de assinatura deve ter ao menos 32 bytes")
    return key


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    fingerprint = subparsers.add_parser("fingerprint")
    fingerprint.add_argument("--root", type=Path, required=True)
    issue = subparsers.add_parser("issue")
    verify = subparsers.add_parser("verify")
    for command in (issue, verify):
        command.add_argument("--root", type=Path, required=True)
        command.add_argument("--artifact", type=Path, required=True)
        command.add_argument("--project", required=True)
        command.add_argument("--key-file", type=Path, required=True)
    issue.add_argument("--ttl", type=int, default=900)
    issue.add_argument("--output", type=Path, required=True)
    verify.add_argument("--proof", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "fingerprint":
            print(json.dumps(source_fingerprint(args.root), sort_keys=True))
            return 0
        key = read_key(args.key_file)
        if args.command == "issue":
            proof = issue_proof(args.root, args.artifact, args.project, key, args.ttl)
            args.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
            os.chmod(args.output, 0o600)
            print(proof["proof_id"])
            return 0
        proof = json.loads(args.proof.read_text())
        verify_proof(proof, args.root, args.artifact, args.project, key)
        print(proof["proof_id"])
        return 0
    except (OSError, subprocess.CalledProcessError, ValueError, ProofError) as error:
        print(f"BLOQUEIA: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
