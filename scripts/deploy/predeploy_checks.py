#!/usr/bin/env python3
"""Checks puros usados pelo gate pre-deploy do WorkDev.

O modulo nao faz deploy, nao reinicia servicos e nunca imprime o conteudo de
um segredo. Cada subcomando retorna apenas 0 (OK) ou 1 (BLOQUEIA).
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path


SECRET_PATTERNS = (
    re.compile(r"sk-" + r"proj-[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-" + r"or-v1-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[opusr]_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"sb_" + r"secret_[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[A-Z0-9]{16}"),
    re.compile(r"-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

IGNORED_PREFIXES = ("skills/",)
IGNORED_NAMES = {"pnpm-lock.yaml", "package-lock.json", "yarn.lock"}


def tracked_files(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    paths = completed.stdout.decode(errors="surrogateescape").split("\0")
    return [root / path for path in paths if path]


def secret_files(root: Path) -> list[str]:
    findings: list[str] = []
    for path in tracked_files(root):
        relative = path.relative_to(root).as_posix()
        if relative in IGNORED_NAMES or relative.startswith(IGNORED_PREFIXES):
            continue
        if path.name == ".env" or path.suffix in {".pem", ".key", ".p12"}:
            findings.append(relative)
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            findings.append(relative)
    return sorted(set(findings))


def python_syntax_errors(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for base in paths:
        for path in sorted(base.rglob("*.py")) if base.exists() else []:
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeDecodeError, OSError) as error:
                errors.append(f"{path}: {type(error).__name__}")
    return errors


def listening_pids(ss_output: str) -> set[int]:
    return {int(pid) for pid in re.findall(r"pid=(\d+)", ss_output)}


def valid_port_pids(pids: set[int], main_pid: int) -> bool:
    if len(pids) > 1:
        return False
    if main_pid > 0:
        return pids == {main_pid}
    return not pids


def paths_outside_root(root: Path, names: list[str]) -> list[str]:
    resolved_root = root.resolve()
    outside: list[str] = []
    for name in names:
        candidate = (resolved_root / name).resolve(strict=False)
        if not candidate.is_relative_to(resolved_root):
            outside.append(name)
    return outside


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    secrets = subparsers.add_parser("secrets")
    secrets.add_argument("root", type=Path)
    syntax = subparsers.add_parser("python-syntax")
    syntax.add_argument("paths", nargs="+", type=Path)
    port = subparsers.add_parser("port-pids")
    port.add_argument("--main-pid", type=int, default=0)
    scope = subparsers.add_parser("scope")
    scope.add_argument("root", type=Path)
    scope.add_argument("paths", nargs="*")
    args = parser.parse_args()

    if args.command == "secrets":
        findings = secret_files(args.root)
        print("\n".join(findings))
        return 1 if findings else 0
    if args.command == "python-syntax":
        errors = python_syntax_errors(args.paths)
        print("\n".join(errors))
        return 1 if errors else 0
    if args.command == "port-pids":
        pids = listening_pids(sys.stdin.read())
        print(" ".join(str(pid) for pid in sorted(pids)))
        return 0 if valid_port_pids(pids, args.main_pid) else 1
    outside = paths_outside_root(args.root, args.paths)
    print("\n".join(outside))
    return 1 if outside else 0


if __name__ == "__main__":
    raise SystemExit(main())
