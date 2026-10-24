"""Política de egresso do contexto de Build (plano de correção, achado 7).

Decide se um prompt pode sair da VPS rumo a um runtime, e em que condições.
Hoje o mesmo texto sai igual para `local-code` (loopback, 127.0.0.1) e para uma
GPU alugada de terceiro — este módulo é o que separa os dois casos.

Três regras, em ordem de dureza:

1. **Projeto `restricted` nunca vai para runtime remoto.** Sem flag, sem
   consentimento, sem exceção. Se o dado não pode sair, não sai.
2. **Runtime remoto exige consentimento explícito** — variável de ambiente
   ligada E evento registrado na run. Ligar a variável sozinha não basta:
   consentimento é por execução e fica na trilha de auditoria.
3. **Runtime remoto sempre passa por redaction.** Mesmo com tudo autorizado.

`local-code` é isento das regras 2 e 3 por ser loopback: o texto não deixa a
máquina. Se um dia existir runtime local em outra máquina, ele entra como
remoto — o critério é `kind == KIND_GPU`, não o nome.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.backlog import BacklogItem
from app.models.handoff import AgentRun, AgentRunEvent
from app.models.project import Project
from app.services import agent_runtimes, context_redaction
from app.services.agent_runtimes import KIND_GPU
from app.services.context_redaction import RedactionResult


CLASSIFICATION_INTERNAL = "internal"
CLASSIFICATION_RESTRICTED = "restricted"

VALID_CLASSIFICATIONS = frozenset(
    {CLASSIFICATION_INTERNAL, CLASSIFICATION_RESTRICTED}
)

CONSENT_EVENT = "build.egress_consent"

REMOTE_CONTEXT_ENV = "WORKDEV_OLLAMA_ALLOW_REMOTE_CONTEXT"


class EgressDenied(RuntimeError):
    """Egresso recusado. Vira 409, nunca exceção crua."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class EgressDecision:
    """O que sai, para onde, e o que foi retirado no caminho."""

    prompt: str
    remote: bool
    classification: str
    redaction: RedactionResult | None = None

    @property
    def redaction_summary(self) -> str:
        if self.redaction is None:
            return "redaction não aplicada (runtime local)"
        return context_redaction.summary(self.redaction)


def _remote_allowed_by_env() -> bool:
    import os

    return os.getenv(REMOTE_CONTEXT_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def is_remote(runtime_id: str) -> bool:
    """Runtime que faz o texto deixar a máquina.

    Critério é o `kind`, não o nome: um runtime local em OUTRA máquina também
    seria egresso, e passaria a valer a política inteira.
    """
    runtime = agent_runtimes.get_runtime(runtime_id)
    return runtime is not None and runtime.kind == KIND_GPU


def classification_for_run(db: Session, run: AgentRun) -> str:
    """Classificação do projeto dono da run. Ausente = `internal`."""
    projeto = (
        db.query(Project)
        .join(BacklogItem, BacklogItem.project_id == Project.id)
        .filter(BacklogItem.id == run.backlog_id)
        .first()
    )

    if projeto is None:
        # Sem projeto identificável, trate como o caso mais sensível: não dá
        # para afirmar que é `internal` o que não se conseguiu ler.
        return CLASSIFICATION_RESTRICTED

    valor = (projeto.context_classification or "").strip().lower()

    return valor if valor in VALID_CLASSIFICATIONS else CLASSIFICATION_RESTRICTED


def has_consent(db: Session, run: AgentRun, runtime_id: str) -> bool:
    """Consentimento é por run E por runtime: autorizar a Hostinger não
    autoriza a RunPod."""
    evento = (
        db.query(AgentRunEvent)
        .filter(
            AgentRunEvent.run_id == run.id,
            AgentRunEvent.event_type == CONSENT_EVENT,
        )
        .all()
    )

    return any(
        (item.payload or {}).get("runtime_id") == runtime_id
        for item in evento
    )


def record_consent(
    db: Session,
    run: AgentRun,
    runtime_id: str,
    *,
    actor: str,
) -> AgentRunEvent:
    """Registra o consentimento na trilha. Quem, quando, para qual runtime."""
    from app.services.handoff import add_run_event

    runtime = agent_runtimes.get_runtime(runtime_id)
    rotulo = runtime.label if runtime else runtime_id

    return add_run_event(
        db,
        run,
        CONSENT_EVENT,
        f"Egresso de contexto autorizado para {rotulo} por {actor}",
        {"runtime_id": runtime_id, "actor": actor},
    )


def prepare(
    db: Session,
    run: AgentRun,
    runtime_id: str,
    prompt: str,
) -> EgressDecision:
    """Aplica a política e devolve o prompt que pode sair — ou recusa.

    Chamado antes de qualquer envio. A recusa acontece aqui, não no driver:
    depois que o texto entrou no cliente HTTP já é tarde.
    """
    remoto = is_remote(runtime_id)
    classificacao = classification_for_run(db, run)

    if not remoto:
        # Loopback: nada deixa a máquina, nada a redigir nem a consentir.
        return EgressDecision(
            prompt=prompt,
            remote=False,
            classification=classificacao,
        )

    if classificacao == CLASSIFICATION_RESTRICTED:
        raise EgressDenied(
            "context_restricted",
            (
                "Projeto classificado como restrito: o contexto não pode sair "
                "da VPS para um runtime remoto"
            ),
            {"runtime_id": runtime_id, "classification": classificacao},
        )

    if not _remote_allowed_by_env():
        raise EgressDenied(
            "remote_egress_disabled",
            (
                f"Envio de contexto para runtime remoto está desligado; "
                f"defina {REMOTE_CONTEXT_ENV} para habilitar"
            ),
            {"runtime_id": runtime_id},
        )

    if not has_consent(db, run, runtime_id):
        raise EgressDenied(
            "remote_egress_not_consented",
            (
                "Falta consentimento explícito para enviar o contexto desta "
                "execução ao runtime remoto"
            ),
            {"runtime_id": runtime_id},
        )

    resultado = context_redaction.redact(prompt)

    return EgressDecision(
        prompt=resultado.text,
        remote=True,
        classification=classificacao,
        redaction=resultado,
    )
