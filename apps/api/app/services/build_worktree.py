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


# Lidos no import por compatibilidade com quem já os monkeypatcha, mas o valor
# EFETIVO vem de repo_root()/builds_root(), que releem o ambiente a cada
# chamada. Só com constante de import, definir WORKDEV_BUILDS_ROOT no unit do
# systemd não tinha efeito nenhum — e o docstring de ephemeral_worktree
# prometia o contrário.
REPO_ROOT = Path(os.getenv("WORKDEV_REPO_ROOT", "/opt/workdev"))
BUILDS_ROOT = Path(os.getenv("WORKDEV_BUILDS_ROOT", "/opt/workdev-builds"))


def repo_root() -> Path:
    """Raiz do repositório, resolvida na chamada."""
    if REPO_ROOT != Path("/opt/workdev"):
        # Alguém monkeypatchou o módulo: respeita, é o que os testes fazem.
        return REPO_ROOT

    return Path(os.getenv("WORKDEV_REPO_ROOT", "/opt/workdev"))


def builds_root() -> Path:
    """Raiz dos builds isolados, resolvida na chamada."""
    if BUILDS_ROOT != Path("/opt/workdev-builds"):
        return BUILDS_ROOT

    return Path(os.getenv("WORKDEV_BUILDS_ROOT", "/opt/workdev-builds"))

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


def branch_name(run_id: str, attempt: int | None = None) -> str:
    """Nome do branch do build.

    A tentativa entra no nome porque nada é pushado: o branch é o ÚNICO lugar
    onde o commit do build existe. Com o nome dependendo só do `run_id`, um
    redespacho da mesma run apagava o branch anterior com `branch -D` e tornava
    aquele commit inalcançável — o oposto do que o `_remover` promete ao manter
    o branch "para inspeção".
    """
    if attempt is None:
        return f"build/{run_id}"

    return f"build/{run_id}/{attempt}"


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
    attempt: int | None = None,
):
    """Cria a árvore isolada e garante a remoção, inclusive em exceção.

    `repo` e a raiz de builds são resolvidos em tempo de CHAMADA, não como
    default de assinatura: um default seria congelado no import, e aí
    `WORKDEV_REPO_ROOT` definido depois — ou um teste redirecionando o módulo —
    não teria efeito nenhum. Foi exatamente isso que fez uma rodada de testes
    criar worktree no repositório real em vez do temporário.
    """
    repo = repo or repo_root()
    raiz_builds = builds_root()

    raiz_builds.mkdir(parents=True, exist_ok=True)

    destino = raiz_builds / str(run_id)
    branch = branch_name(run_id, attempt)
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

    _preparar_ambiente(destino, repo)

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


# `node_modules` e a config do Vite não são versionados, então `git worktree
# add` não os traz. Sem eles o gate não roda dentro do worktree: `vitest` e
# `vite build` são obrigatórios, e sem dependência nem `VITE_SUPABASE_URL` todo
# build caía em `blocked` por ambiente ausente, não por código ruim.
#
# REGRA QUE NÃO PODE SER QUEBRADA: o gate NUNCA invoca `pnpm` dentro de um
# worktree. O pnpm confere o `node_modules` antes de rodar script, vê um
# diretório de outro projeto e decide purgar — e como aqui é symlink para o do
# repositório real, isso apagaria as dependências de produção. Medido em
# 2026-09-10 (`ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`, que só não purgou
# por falta de TTY). Quem garante a regra é `GatePaths.node_bin`, em test_gate.
#
# São symlinks e não cópia porque o store tem gigabytes. O acoplamento que isso
# deixa, dito em vez de escondido: o worktree compartilha o `node_modules` do
# repo real, cache de build incluído. O isolamento da fatia 3 vale para o
# CÓDIGO, não para a árvore de dependências.
DEPENDENCY_LINKS: tuple[str, ...] = (
    "node_modules",
    "apps/web/node_modules",
)

# Lista EXPLÍCITA, nunca glob. `.env.local` está fora de propósito: ele tem
# precedência no Vite e já vazou `VITE_API_URL=localhost` para bundle de
# produção uma vez (registrado no CLAUDE.md). O `.env` do apps/api também fica
# fora — o worktree não precisa de credencial de banco para rodar o gate.
CONFIG_FILES: tuple[str, ...] = (
    "apps/web/.env",
    "apps/web/.env.development",
    "apps/web/.env.production",
)


def _preparar_ambiente(destino: Path, repo: Path) -> dict[str, list[str]]:
    """Liga dependências e materializa a config que o gate precisa."""
    ligados: list[str] = []
    copiados: list[str] = []

    for relativo in DEPENDENCY_LINKS:
        origem = repo / relativo
        alvo = destino / relativo

        if not origem.exists() or alvo.exists():
            continue

        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.symlink_to(origem, target_is_directory=True)
        ligados.append(relativo)

    for relativo in CONFIG_FILES:
        origem = repo / relativo
        alvo = destino / relativo

        if not origem.is_file() or alvo.exists():
            continue

        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem, alvo)
        copiados.append(relativo)

    return {"links": ligados, "config": copiados}


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


def diffstat(worktree: Worktree, *, desde: str | None = None) -> str:
    """Resumo do que mudou, incluindo arquivo NOVO.

    Chamado DEPOIS do commit, com `desde=base_sha`: comparar dois commits vê
    arquivo novo naturalmente. Antes disto era `git diff --stat HEAD` na árvore
    suja, que só enxerga o que o índice já conhece — um build que apenas cria
    arquivos devolvia resumo vazio na UI, com `files` preenchido.

    Marcar os untracked com `--intent-to-add` resolveria o diff e estragaria o
    commit: os arquivos entram no índice com conteúdo vazio e é assim que são
    commitados. Foi testado e descartado.
    """
    if desde:
        return _git(
            ["diff", "--stat", f"{desde}..HEAD"], worktree.path
        ).stdout.strip()

    return _git(["diff", "--stat", "HEAD"], worktree.path).stdout.strip()


def commit(
    worktree: Worktree,
    message: str,
    *,
    paths: list[str] | None = None,
) -> str:
    """Commita no branch do worktree. Nunca faz push — não existe rede aqui.

    Com `paths`, adiciona EXATAMENTE os caminhos do envelope. Isso não é
    detalhe: `git add -A` varria também o que `_preparar_ambiente` cria para o
    gate rodar — e o symlink `node_modules` entrou num commit de build na
    validação de 2026-09-10. O `.gitignore` não o barrou porque o padrão é
    `node_modules/`, com barra, que casa diretório e não casa symlink.

    O mesmo `add -A` levaria a config do Vite copiada para o worktree se ela
    não fosse ignorada. Um commit de build deve conter o que o modelo propôs,
    nada mais — o envelope é o contrato, e o que não está nele não entra.
    """
    if paths:
        _git_ok(["add", "--", *paths], worktree.path, "git_add_failed")
    else:
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
