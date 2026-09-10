"""Worktree efêmero por run de Build (ADR 005).

Por que não aplicar o patch direto em `/opt/workdev`: a árvore principal é a que
o operador usa e a que alimenta o `prepare` do deploy (o fingerprint sai de
`apps/web/dist`). Um build de agente que falhasse no meio deixaria a árvore
suja, e um `git checkout` de recuperação atropelaria trabalho humano em curso.

Então cada run ganha uma árvore própria, descartável, criada a partir de um SHA
conhecido e removida ao final — inclusive quando dá errado. O branch fica para
inspeção; o diretório não.

Nada aqui roda comando vindo do modelo. Os únicos processos executados são git,
com argumentos montados por este módulo.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.services.build_envelope import BuildEnvelope


REPO_ROOT = Path(os.getenv("WORKDEV_REPO_ROOT", "/opt/workdev"))
BUILDS_ROOT = Path(os.getenv("WORKDEV_BUILDS_ROOT", "/opt/workdev-builds"))

GIT_TIMEOUT_SECONDS = 120

# Identidade dos commits de agente. Deixa explícito na trilha do git quem
# produziu a mudança — não se passa por commit humano.
COMMIT_AUTHOR_NAME = "WorkDev Build Worker"
COMMIT_AUTHOR_EMAIL = "build-worker@workdev.local"


class WorktreeError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class Worktree:
    run_id: str
    path: Path
    branch: str
    base_sha: str


def _git(
    args: list[str],
    cwd: Path,
    *,
    timeout: int = GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _git_ok(args: list[str], cwd: Path, code: str) -> str:
    resultado = _git(args, cwd)

    if resultado.returncode != 0:
        raise WorktreeError(
            code,
            f"git {' '.join(args[:2])} falhou: "
            f"{(resultado.stderr or resultado.stdout).strip()[:300]}",
            {"returncode": resultado.returncode},
        )

    return resultado.stdout.strip()


def head_sha(repo: Path | None = None) -> str:
    return _git_ok(["rev-parse", "HEAD"], repo or REPO_ROOT, "head_unavailable")


def branch_name(run_id: str) -> str:
    return f"build/{run_id}"


def _remover(worktree_path: Path, branch: str, repo: Path) -> None:
    """Remove o diretório do worktree. O branch permanece, de propósito."""
    _git(["worktree", "remove", "--force", str(worktree_path)], repo)

    # `git worktree remove` recusa em alguns estados (índice travado, arquivo
    # não rastreado). O diretório é descartável, então o fallback é seguro.
    if worktree_path.exists():
        shutil.rmtree(worktree_path, ignore_errors=True)

    _git(["worktree", "prune"], repo)


@contextmanager
def ephemeral_worktree(
    run_id: str,
    *,
    repo: Path | None = None,
    base: str | None = None,
):
    """Cria a árvore isolada e garante a remoção, inclusive em exceção.

    `repo` e a raiz de builds são resolvidos em tempo de CHAMADA, não como
    default de assinatura: um default seria congelado no import, e aí
    `WORKDEV_REPO_ROOT` definido depois — ou um teste redirecionando o módulo —
    não teria efeito nenhum. Foi exatamente isso que fez uma rodada de testes
    criar worktree no repositório real em vez do temporário.
    """
    repo = repo or REPO_ROOT
    builds_root = BUILDS_ROOT

    builds_root.mkdir(parents=True, exist_ok=True)

    destino = builds_root / str(run_id)
    branch = branch_name(run_id)
    base_sha = base or head_sha(repo)

    if destino.exists():
        # Sobra de uma execução anterior que morreu de forma abrupta.
        _remover(destino, branch, repo)

    # Um branch remanescente da tentativa anterior impediria o `-b`.
    _git(["branch", "-D", branch], repo)

    _git_ok(
        ["worktree", "add", "--detach", str(destino), base_sha],
        repo,
        "worktree_add_failed",
    )
    _git_ok(["checkout", "-b", branch], destino, "branch_create_failed")

    worktree = Worktree(
        run_id=str(run_id),
        path=destino,
        branch=branch,
        base_sha=base_sha,
    )

    try:
        yield worktree
    finally:
        _remover(destino, branch, repo)


def write_files(worktree: Worktree, envelope: BuildEnvelope) -> list[str]:
    """Materializa os arquivos do envelope dentro do worktree.

    Segunda barreira do path: mesmo já validado pelo envelope, o caminho é
    resolvido e conferido contra a raiz. Symlink apontando para fora da árvore
    é o caso que a validação de string sozinha não pega.
    """
    raiz = worktree.path.resolve()
    tocados: list[str] = []

    for arquivo in envelope.files:
        destino = (raiz / arquivo.path).resolve()

        if not destino.is_relative_to(raiz):
            raise WorktreeError(
                "path_escapes_worktree",
                f"Caminho resolve para fora do worktree: {arquivo.path}",
                {"path": arquivo.path},
            )

        if arquivo.action == "delete":
            if destino.exists():
                destino.unlink()
                tocados.append(arquivo.path)
            continue

        if arquivo.content is None:
            raise WorktreeError(
                "content_missing",
                f"Ação '{arquivo.action}' exige conteúdo: {arquivo.path}",
                {"path": arquivo.path},
            )

        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(arquivo.content, encoding="utf-8")
        tocados.append(arquivo.path)

    return tocados


def has_changes(worktree: Worktree) -> bool:
    return bool(_git(["status", "--porcelain"], worktree.path).stdout.strip())


def diffstat(worktree: Worktree) -> str:
    return _git(["diff", "--stat", "HEAD"], worktree.path).stdout.strip()


def commit(worktree: Worktree, message: str) -> str:
    """Commita no branch do worktree. Nunca faz push — não existe rede aqui."""
    _git_ok(["add", "-A"], worktree.path, "git_add_failed")

    resultado = _git(
        [
            "-c",
            f"user.name={COMMIT_AUTHOR_NAME}",
            "-c",
            f"user.email={COMMIT_AUTHOR_EMAIL}",
            "commit",
            "-m",
            message,
        ],
        worktree.path,
    )

    if resultado.returncode != 0:
        raise WorktreeError(
            "commit_failed",
            f"Commit falhou: "
            f"{(resultado.stderr or resultado.stdout).strip()[:300]}",
        )

    return _git_ok(["rev-parse", "HEAD"], worktree.path, "head_unavailable")
