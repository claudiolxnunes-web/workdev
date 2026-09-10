"""Execução isolada de um Build proposto por runtime Ollama (ADR 005).

Este módulo é o "quem aplica" do ADR: recebe o texto que o modelo devolveu e o
transforma em commit num branch descartável, passando pelo gate. O modelo nunca
executa nada — cada passo aqui é código da VPS, com argumentos montados pela
VPS.

Sequência, e o motivo de cada corte:

1. `parse_envelope` — recusa antes de tocar em disco.
2. worktree efêmero — a árvore de `/opt/workdev` não é envolvida.
3. `write_files` — segunda checagem de path, contra a raiz resolvida.
4. `git apply --check` equivalente: se não houve mudança, não há o que commitar.
5. gate **dentro do worktree** — evidência amarrada ao SHA do que rodou.
6. commit no branch, sem push. Gate PASS → `review`; FAIL → `blocked`.

`completed` continua inalcançável por aqui: quem conclui é a revisão
independente, como manda o ADR 004.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.handoff import AgentRun
from app.services import build_worktree
from app.services.build_envelope import (
    BuildEnvelope,
    EnvelopeError,
    parse_envelope,
)
from app.services.build_worktree import WorktreeError
from app.services.test_gate import (
    GateEvidence,
    GatePaths,
    execute_gate,
    persist_gate_evidence,
)


def build_enabled() -> bool:
    """Interruptor mestre. Desligado, o comportamento é o de antes do worker."""
    return os.getenv("WORKDEV_OLLAMA_BUILD_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def max_attempts() -> int:
    try:
        valor = int(os.getenv("WORKDEV_OLLAMA_BUILD_MAX_ATTEMPTS", "3"))
    except ValueError:
        valor = 3
    return max(1, min(10, valor))


@dataclass
class BuildOutcome:
    """O que a execução produziu, para virar eventos e transição de run."""

    ok: bool
    code: str
    message: str
    branch: str | None = None
    commit_sha: str | None = None
    base_sha: str | None = None
    files: list[str] = field(default_factory=list)
    diffstat: str | None = None
    gate_passed: bool | None = None
    gate_evidence: GateEvidence | None = None
    details: dict = field(default_factory=dict)

    @property
    def next_status(self) -> str:
        """Status alvo da run. Nunca `completed` — isso é da revisão."""
        if not self.ok:
            return "blocked"
        return "review" if self.gate_passed else "blocked"


def execute_build(
    run: AgentRun,
    response_text: str,
    *,
    run_gate: bool = True,
    attempt: int | None = None,
) -> BuildOutcome:
    """Texto do modelo → commit num branch isolado, ou recusa explicada.

    Não levanta: toda falha vira `BuildOutcome` com código. Um build que falha é
    resultado normal do sistema, não exceção.
    """
    try:
        envelope = parse_envelope(response_text)
    except EnvelopeError as error:
        return BuildOutcome(
            ok=False,
            code=error.code,
            message=error.message,
            details=error.details,
        )

    if not envelope.files:
        return BuildOutcome(
            ok=False,
            code="envelope_without_changes",
            message="Envelope não propõe nenhuma alteração de arquivo",
        )

    try:
        return _executar(run, envelope, run_gate=run_gate, attempt=attempt)
    except WorktreeError as error:
        return BuildOutcome(
            ok=False,
            code=error.code,
            message=error.message,
            details=error.details,
        )
    except Exception as error:  # fail-closed: nada passa por acidente
        return BuildOutcome(
            ok=False,
            code="build_failed",
            message=f"Falha inesperada na execução: {type(error).__name__}",
        )


def _executar(
    run: AgentRun,
    envelope: BuildEnvelope,
    *,
    run_gate: bool,
    attempt: int | None = None,
) -> BuildOutcome:
    # A tentativa entra no nome do branch: sem ela, redespachar a mesma run
    # apagava o branch anterior e tornava aquele commit inalcançável — e o
    # branch é o único lugar onde o commit do build existe, já que nada é
    # pushado.
    with build_worktree.ephemeral_worktree(
        str(run.id), attempt=attempt
    ) as worktree:
        tocados = build_worktree.write_files(worktree, envelope)

        if not build_worktree.has_changes(worktree):
            return BuildOutcome(
                ok=False,
                code="no_effective_change",
                message=(
                    "O envelope foi aplicado mas não alterou nada: o conteúdo "
                    "proposto já é o conteúdo atual"
                ),
                branch=worktree.branch,
                base_sha=worktree.base_sha,
                files=tocados,
            )

        evidencia: GateEvidence | None = None
        gate_passou: bool | None = None

        if run_gate:
            evidencia = execute_gate(run, GatePaths(root=worktree.path))
            gate_passou = evidencia.passed

        commit_sha = build_worktree.commit(
            worktree,
            _mensagem_de_commit(run, envelope, gate_passou),
        )

        # Depois do commit e contra a base: é o que enxerga arquivo novo sem
        # mexer no índice antes da hora.
        diffstat = build_worktree.diffstat(worktree, desde=worktree.base_sha)

        return BuildOutcome(
            ok=True,
            code="build_committed",
            message=(
                f"{len(tocados)} arquivo(s) em {worktree.branch}"
                + ("" if gate_passou is None else
                   f"; gate {'aprovado' if gate_passou else 'reprovado'}")
            ),
            branch=worktree.branch,
            commit_sha=commit_sha,
            base_sha=worktree.base_sha,
            files=tocados,
            diffstat=diffstat,
            gate_passed=gate_passou,
            gate_evidence=evidencia,
        )


def _mensagem_de_commit(
    run: AgentRun,
    envelope: BuildEnvelope,
    gate_passou: bool | None,
) -> str:
    """Mensagem que não se disfarça de commit humano."""
    resumo = envelope.summary.strip().splitlines()[0][:72]
    selo = {
        True: "gate: aprovado",
        False: "gate: reprovado",
        None: "gate: não executado",
    }[gate_passou]

    return (
        f"build({run.agent}): {resumo}\n\n"
        f"Run: {run.id}\n"
        f"Executor: {run.agent} (runtime Ollama, ADR 005)\n"
        f"{selo}\n\n"
        "Commit gerado pelo worker de build isolado a partir de um envelope "
        "estruturado. Não promovido: revisão independente pendente."
    )


def persist_outcome(
    db: Session,
    run: AgentRun,
    outcome: BuildOutcome,
) -> None:
    """Grava a evidência de gate da execução isolada, se houve."""
    if outcome.gate_evidence is not None:
        persist_gate_evidence(db, outcome.gate_evidence)


def outcome_payload(outcome: BuildOutcome) -> dict:
    """Payload do evento da run. Sem conteúdo de arquivo — só o que auditar."""
    return {
        "code": outcome.code,
        "branch": outcome.branch,
        "commit_sha": outcome.commit_sha,
        "base_sha": outcome.base_sha,
        "files": outcome.files,
        "diffstat": outcome.diffstat,
        "gate_passed": outcome.gate_passed,
        **outcome.details,
    }
