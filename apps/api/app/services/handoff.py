from datetime import datetime, timezone
from typing import Any
import os
from uuid import UUID

from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, Field

from app.models.adr import ADR
from app.models.backlog import BacklogItem
from app.models.decision import Decision
from app.models.handoff import (
    AgentRun,
    AgentRunEvent,
    AgentRunReview,
    ExecutionPlan,
)
from app.models.knowledge import KnowledgeEntry
from app.models.project import Project
from app.models.subtask import BacklogSubtask
from app.services.agent_runtimes import OLLAMA_AGENT_IDS


PLAN_EDITABLE = {"draft", "needs_revision"}
ACTIVE_RUN_STATUSES = {"queued", "running", "blocked", "review"}
TRANSFERABLE_RUN_STATUSES = {"queued", "running", "blocked"}

# Agentes com CLI própria e sessão tmux persistente na VPS.
CLI_AGENTS = {
    "codex",
    "claude",
    "kimi",
    "qwen",
    "gemini",
}

# Identidades de runtime Ollama (local e GPU). São estáveis e independentes do
# modelo carregado; ficam fora do AUTO até haver benchmark.
SUPPORTED_AGENTS = CLI_AGENTS | set(OLLAMA_AGENT_IDS)

# Quem CONSEGUE emitir veredito — capacidade implementada, não preferência de
# qualidade. Hoje são os agentes CLI: todos têm sessão tmux e a CLI
# `workdev_agent.py verdict`, que é o único caminho até
# `POST /runs/{id}/reviews`.
#
# A distinção é deliberada e não deve virar hierarquia. A escolha de executor e
# revisor é sempre do operador; a UI ordena e recomenda, nunca proíbe por gosto.
# O que este conjunto barra é outra coisa: escolher como revisor uma identidade
# sem canal de veredito não produz revisão pior — produz uma run parada em
# `review` para sempre, porque ninguém dispara o veredito. Isso é defeito.
#
# Para habilitar runtime Ollama como revisor não há regra a derrubar aqui: falta
# implementar o canal (fatia opcional B de docs/plano-correcao-ollama.md).
AGENTS_WITH_REVIEW_CHANNEL = frozenset(CLI_AGENTS)

SUPPORTED_ROUTING_MODES = {"manual", "auto"}
COMPLEXITY_LEVELS = {"low", "medium", "high", "critical"}

# `running` não fecha direto em `completed`: terminar a execução entrega a run
# ao revisor independente (`review`), e só a revisão — depois dos gates
# objetivos — conclui. Rejeição devolve de `review` para `running`.
RUN_TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"blocked", "review", "failed", "cancelled"},
    "blocked": {"running", "cancelled", "failed"},
    "review": {"running", "blocked", "completed", "failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}

REVIEW_VERDICTS = {"approved", "rejected"}


class HandoffError(RuntimeError):
    """Erro de contrato do handoff.

    `code` é opcional e existe para o chamador distinguir a causa sem depender
    do texto da mensagem, que é escrito para humanos e muda. As rotas continuam
    devolvendo só a mensagem no corpo HTTP — o código é contrato interno e de
    teste, não uma mudança na resposta da API.
    """

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class AutoRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "auto-runtime.v2"
    run_id: str
    session: str
    timeout_seconds: int = Field(ge=60, le=86400)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_routing_metadata(
    agent: str,
    routing_mode: str,
    complexity: str | None,
    complexity_score: int | None,
) -> None:
    if not agent:
        if routing_mode == "auto":
            raise HandoffError(
                "Roteamento AUTO precisa resolver um agente antes do Build"
            )
        raise HandoffError("Agente é obrigatório")

    if agent not in SUPPORTED_AGENTS:
        raise HandoffError(
            "Agente inválido; escolha um dos agentes suportados: "
            + ", ".join(sorted(SUPPORTED_AGENTS))
        )

    if routing_mode not in SUPPORTED_ROUTING_MODES:
        raise HandoffError(
            "routing_mode inválido; escolha manual ou auto"
        )

    # Segunda barreira, além do filtro do roteador: runtime Ollama só entra em
    # execução por escolha manual do usuário.
    if routing_mode == "auto" and agent in OLLAMA_AGENT_IDS:
        raise HandoffError(
            f"{agent} é runtime Ollama e só aceita seleção manual nesta fase; "
            "o AUTO não pode escolhê-lo"
        )

    if complexity is not None and complexity not in COMPLEXITY_LEVELS:
        raise HandoffError(
            "complexity inválida; escolha low, medium, high ou critical"
        )

    if complexity_score is not None:
        if not isinstance(complexity_score, int):
            raise HandoffError("complexity_score precisa ser inteiro")
        if not 0 <= complexity_score <= 100:
            raise HandoffError(
                "complexity_score precisa estar entre 0 e 100"
            )


def validate_review_pair(executor: str, reviewer: str | None) -> str:
    """Garante revisão independente: quem executa nunca é quem aprova.

    Vale tanto no envio ao Build quanto na revisão final e nas trocas
    auditadas de agente — é a mesma regra, aplicada em um lugar só.
    """
    if not reviewer:
        raise HandoffError(
            "Revisor é obrigatório: escolha um agente diferente do executor "
            "antes de enviar ao Build"
        )

    if reviewer not in SUPPORTED_AGENTS:
        raise HandoffError(
            "Revisor inválido; escolha um dos agentes suportados",
            "reviewer_not_supported",
        )

    # Barra por capacidade ausente, não por preferência: sem canal de veredito
    # ninguém dispara POST /runs/{id}/reviews e a run fica parada em `review`
    # para sempre. A mensagem diz o motivo técnico de propósito — o operador
    # continua dono da escolha, e precisa saber que esta não é uma opção pior,
    # é uma opção que trava.
    if reviewer not in AGENTS_WITH_REVIEW_CHANNEL:
        raise HandoffError(
            f"'{reviewer}' não tem canal de veredito implementado; a run "
            "ficaria parada em review para sempre. Escolha um agente com CLI "
            "e sessão tmux: "
            + ", ".join(sorted(AGENTS_WITH_REVIEW_CHANNEL)),
            "reviewer_has_no_review_channel",
        )

    if reviewer == executor:
        raise HandoffError(
            "Executor e revisor precisam ser agentes diferentes; "
            "o executor não aprova o próprio trabalho"
        )

    return reviewer



def _lista_de_texto(valor):
    if not valor:
        return []
    saida = []
    for e in valor:
        if isinstance(e, str):
            saida.append(e)
        elif isinstance(e, dict):
            saida.append(e.get("item") or e.get("texto") or e.get("descricao") or str(e))
        else:
            saida.append(str(e))

    return saida



def create_plan(
    db: Session,
    data: dict[str, Any],
) -> ExecutionPlan:
    task = db.query(BacklogItem).filter(
        BacklogItem.id == data["backlog_id"]
    ).first()

    if not task:
        raise HandoffError("Task do backlog não encontrada")

    # Check for duplicate active/approved plan
    active_plan = db.query(ExecutionPlan).filter(
        ExecutionPlan.backlog_id == task.id,
        ExecutionPlan.status.in_({"draft", "needs_revision", "approved"})
    ).first()
    if active_plan:
        raise HandoffError(
            f"Já existe um plano ativo ou aprovado para esta tarefa (status: {active_plan.status})"
        )

    version = db.query(
        func.coalesce(func.max(ExecutionPlan.version), 0)
    ).filter(
        ExecutionPlan.backlog_id == task.id
    ).scalar() + 1

    plan = ExecutionPlan(
        backlog_id=task.id,
        version=version,
        status="draft",
        title=(data.get("title") or task.title).strip(),
        objective=data["objective"].strip(),
        scope=(data.get("scope") or "").strip() or None,
        constraints=_lista_de_texto(data.get("constraints")),
        acceptance_criteria=_lista_de_texto(data.get("acceptance_criteria")),
        validation_steps=_lista_de_texto(data.get("validation_steps")),
        implementation_notes=(
            (data.get("implementation_notes") or "").strip() or None
        ),
        created_by=data.get("created_by") or "ai_hub",
    )

    db.add(plan)
    db.commit()
    db.refresh(plan)

    return plan


def update_plan(
    db: Session,
    plan: ExecutionPlan,
    data: dict[str, Any],
) -> ExecutionPlan:
    if plan.status not in PLAN_EDITABLE:
        raise HandoffError(
            "Somente planos em rascunho ou revisão podem ser alterados"
        )

    next_status = data.pop("status", None)

    if (
        {"title", "objective"} & data.keys()
        and plan.status != "draft"
    ):
        raise HandoffError(
            "Título e objetivo só podem ser alterados em planos Draft"
        )

    if next_status:
        if next_status != "discarded" or plan.status != "draft":
            raise HandoffError(
                "Somente planos Draft podem ser descartados"
            )
        plan.status = next_status

    for field, value in data.items():
        if value is not None:
            setattr(
                plan,
                field,
                value.strip() if isinstance(value, str) else value,
            )

    plan.updated_at = _now()

    db.commit()
    db.refresh(plan)

    return plan


def approve_plan(
    db: Session,
    plan: ExecutionPlan,
    *,
    allow_oversized: bool = False,
) -> ExecutionPlan:
    if plan.status not in PLAN_EDITABLE:
        raise HandoffError(
            f"Plano não pode ser aprovado no estado {plan.status}"
        )

    if not plan.acceptance_criteria:
        raise HandoffError(
            "Inclua pelo menos um critério de aceite antes de aprovar"
        )

    if not plan.validation_steps:
        raise HandoffError(
            "Inclua pelo menos uma etapa de validação antes de aprovar"
        )

    # Trabalho grande só é aprovado fatiado: cada unidade precisa ter objetivo
    # único e gate próprio, senão a falha não tem como ser localizada. O
    # operador pode assumir a exceção explicitamente com allow_oversized.
    if not allow_oversized:
        from app.services.plan_granularity import assess

        granularidade = assess(plan, load_subtasks(db, plan.backlog_id))

        if granularidade["requires_decomposition"]:
            sinais = "; ".join(granularidade["signals"])
            raise HandoffError(
                f"Plano grande demais para uma execução só ({sinais}). "
                f"São exigidas {granularidade['required_slices']} fatias "
                f"auditáveis e há {granularidade['covered_slices']} coberta(s) "
                f"por subtask própria "
                f"(de {granularidade['subtask_count']} subtask(s) no total). "
                "Decomponha antes de aprovar — use "
                f"POST /api/handoffs/plans/{plan.id}/decompose ou aprove com "
                "force=true assumindo a exceção."
            )

    (
        db.query(ExecutionPlan)
        .filter(
            ExecutionPlan.backlog_id == plan.backlog_id,
            ExecutionPlan.status == "approved",
            ExecutionPlan.id != plan.id,
        )
        .update(
            {
                "status": "superseded",
                "updated_at": _now(),
            },
            synchronize_session=False,
        )
    )

    plan.status = "approved"
    plan.approved_at = _now()
    plan.updated_at = _now()

    # Aprovar o plano nunca inicia execução nem escolhe agente automaticamente.
    # O roteamento permanece disponível como recomendação separada; criar Build
    # exige ação explícita do usuário.
    db.commit()
    db.refresh(plan)

    return plan


def decompose_plan(
    db: Session,
    plan: ExecutionPlan,
) -> list[BacklogSubtask]:
    """Materializa as fatias sugeridas como subtasks da task do plano.

    Idempotente por título: rodar de novo não duplica fatia já criada.
    """
    from app.services.plan_granularity import assess, suggest_slices

    existentes = load_subtasks(db, plan.backlog_id)
    granularidade = assess(plan, existentes)

    if not granularidade["oversized"]:
        raise HandoffError(
            "Plano já está no tamanho de uma unidade auditável; não há o que "
            "decompor"
        )

    fatias = suggest_slices(plan)

    if len(fatias) < 2:
        raise HandoffError(
            "Não foi possível derivar fatias do escopo; enumere as frentes no "
            "escopo do plano (1., 2., 3.) e tente de novo"
        )

    titulos = {row.title.strip() for row in existentes}
    proxima_ordem = max(
        (row.execution_order or 0 for row in existentes),
        default=0,
    )
    criadas: list[BacklogSubtask] = []

    for fatia in fatias:
        if fatia["title"] in titulos:
            continue

        proxima_ordem += 1
        subtask = BacklogSubtask(
            backlog_id=plan.backlog_id,
            title=fatia["title"],
            description=fatia["description"],
            status="todo",
            execution_order=proxima_ordem,
        )
        db.add(subtask)
        criadas.append(subtask)

    db.commit()

    for subtask in criadas:
        db.refresh(subtask)

    return criadas


def add_run_event(
    db: Session,
    run: AgentRun,
    event_type: str,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AgentRunEvent:
    event = AgentRunEvent(
        run_id=run.id,
        event_type=event_type,
        message=message,
        payload=payload or {},
    )

    db.add(event)
    db.flush()

    return event


def queue_build(
    db: Session,
    plan: ExecutionPlan,
    agent: str,
    *,
    reviewer: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    routing_mode: str = "manual",
    complexity: str | None = None,
    complexity_score: int | None = None,
    routing_reason: str | None = None,
) -> tuple[AgentRun, AgentRunEvent]:
    if plan.status != "approved":
        raise HandoffError(
            "O plano precisa estar aprovado antes do Build"
        )

    _validate_routing_metadata(
        agent,
        routing_mode,
        complexity,
        complexity_score,
    )

    reviewer = validate_review_pair(agent, reviewer)

    active = db.query(AgentRun).filter(
        AgentRun.backlog_id == plan.backlog_id,
        AgentRun.status.in_(ACTIVE_RUN_STATUSES),
    ).first()

    if active:
        raise HandoffError(
            f"A task já possui uma execução ativa ({active.status})"
        )

    run = AgentRun(
        plan_id=plan.id,
        backlog_id=plan.backlog_id,
        agent=agent,
        reviewer_agent=reviewer,
        review_attempts=0,
        model=model,
        reasoning_effort=reasoning_effort,
        complexity=complexity,
        complexity_score=complexity_score,
        routing_mode=routing_mode,
        routing_reason=routing_reason,
        status="queued",
    )

    db.add(run)
    db.flush()

    routing_payload = {
        "agent": agent,
        "reviewer_agent": reviewer,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "routing_mode": routing_mode,
        "complexity": complexity,
        "complexity_score": complexity_score,
        "routing_reason": routing_reason,
    }

    routing_payload = {
        key: value
        for key, value in routing_payload.items()
        if value is not None
    }

    event = add_run_event(
        db,
        run,
        "build.queued",
        f"Build enviado para {agent} (revisor: {reviewer})",
        routing_payload,
    )

    task = db.query(BacklogItem).filter(
        BacklogItem.id == plan.backlog_id
    ).first()

    if task:
        task.owner = agent
        task.updated_at = _now()

    db.commit()
    db.refresh(run)
    db.refresh(event)

    return run, event


def update_run(
    db: Session,
    run: AgentRun,
    data: dict[str, Any],
) -> tuple[AgentRun, AgentRunEvent | None]:
    next_status = data.pop("status", None)
    message = data.pop("message", None)

    event = None

    if next_status and next_status != run.status:
        allowed = RUN_TRANSITIONS.get(run.status, set())

        if next_status not in allowed:
            raise HandoffError(
                f"Transição inválida: {run.status} → {next_status}"
            )

        # Gate de testes antes de permitir transição para review ou completed
        # FAIL-CLOSED: sem evidência válida → bloqueia
        if next_status in {"review", "completed"}:
            from app.services.test_gate import validate_run_for_status_change

            allowed_by_gate, gate_reason = validate_run_for_status_change(
                db, run, next_status
            )

            if not allowed_by_gate:
                raise HandoffError(
                    f"Gate de testes reprovado: {gate_reason}. "
                    f"Task não pode ir para {next_status} sem testes aprovados."
                )

        previous = run.status
        run.status = next_status
        now = _now()

        if next_status == "running" and not run.started_at:
            run.started_at = now

        if next_status in {
            "completed",
            "failed",
            "cancelled",
        }:
            run.finished_at = now

        event = add_run_event(
            db,
            run,
            f"build.{next_status}",
            message,
            {
                "from": previous,
                "to": next_status,
            },
        )

        task = db.query(BacklogItem).filter(
            BacklogItem.id == run.backlog_id
        ).first()

        if task:
            if next_status in {"running", "review"}:
                task.status = "doing"
            elif next_status in {"blocked", "failed"}:
                task.status = "blocked"
            elif next_status == "completed":
                if task_requires_deploy(db, run.backlog_id):
                    task.status = "doing"
                else:
                    task.status = "done"
                    promote_pending_subtasks(db, task)
            elif (
                next_status == "cancelled"
                and task.status != "done"
            ):
                task.status = "todo"

            task.owner = run.agent
            task.updated_at = now

        if next_status == "running":
            (
                db.query(BacklogSubtask)
                .filter(
                    BacklogSubtask.backlog_id == run.backlog_id,
                    BacklogSubtask.assigned_agent.is_(None),
                )
                .update(
                    {"assigned_agent": run.agent},
                    synchronize_session=False,
                )
            )

    for field in (
        "summary",
        "result",
        "error",
        "branch",
        "commit_sha",
        "deployment_url",
    ):
        if field in data and data[field] is not None:
            setattr(run, field, data[field])

    run.updated_at = _now()

    if not event and message:
        event = add_run_event(
            db,
            run,
            "build.progress",
            message,
        )

    db.commit()
    db.refresh(run)

    if event:
        db.refresh(event)

    return run, event


def transfer_run(
    db: Session,
    run: AgentRun,
    new_agent: str,
    reason: str,
    new_reviewer: str | None = None,
) -> tuple[AgentRun, AgentRun]:
    if new_agent not in SUPPORTED_AGENTS:
        raise HandoffError(
            "Agente inválido; escolha um dos agentes suportados: "
            + ", ".join(sorted(SUPPORTED_AGENTS))
        )

    if new_agent == run.agent:
        raise HandoffError(
            "Escolha um agente diferente do atual para transferir"
        )

    # A transferência preserva o revisor escolhido na aprovação do PLAN, a
    # menos que a troca informe um revisor novo. Se o novo executor for
    # justamente o revisor vigente, a independência some — recusa.
    reviewer = new_reviewer or run.reviewer_agent
    if new_agent == reviewer:
        raise HandoffError(
            f"{new_agent} é o revisor desta execução; informe também um "
            "revisor diferente para transferir a execução para ele"
        )

    if run.status not in TRANSFERABLE_RUN_STATUSES:
        raise HandoffError(
            f"Execução em '{run.status}' não pode ser transferida "
            "(só queued, running ou blocked)"
        )

    plan = db.query(ExecutionPlan).filter(
        ExecutionPlan.id == run.plan_id
    ).first()

    if not plan:
        raise HandoffError(
            "Plano da execução não encontrado"
        )

    previous_agent = run.agent

    cancelled_run, _ = update_run(
        db,
        run,
        {
            "status": "cancelled",
            "message": (
                f"Transferido para {new_agent}: {reason}"
            ),
        },
    )

    new_run, _event = queue_build(
        db,
        plan,
        new_agent,
        reviewer=reviewer,
        routing_mode="manual",
        routing_reason=(
            f"Transferência manual de {previous_agent}: {reason}"
        ),
    )

    add_run_event(
        db,
        new_run,
        "build.transferred",
        f"Transferido de {previous_agent} ({reason})",
        {
            "from_run_id": str(cancelled_run.id),
            "from_agent": previous_agent,
            "to_agent": new_agent,
            "reviewer_agent": reviewer,
            "reviewer_changed": bool(
                new_reviewer and new_reviewer != run.reviewer_agent
            ),
            "reason": reason,
        },
    )

    db.commit()
    db.refresh(new_run)

    return cancelled_run, new_run


def swap_reviewer(
    db: Session,
    run: AgentRun,
    new_reviewer: str,
    reason: str,
) -> tuple[AgentRun, AgentRunEvent]:
    """Troca auditada do revisor sem cancelar a execução em andamento.

    Serve para o caso em que o revisor designado fica indisponível no meio do
    ciclo. Exige justificativa escrita e mantém a regra de independência.
    """
    if run.status not in ACTIVE_RUN_STATUSES:
        raise HandoffError(
            f"Execução em '{run.status}' não aceita troca de revisor"
        )

    reason = (reason or "").strip()

    if not reason:
        raise HandoffError(
            "Troca de revisor exige justificativa escrita"
        )

    validate_review_pair(run.agent, new_reviewer)

    if new_reviewer == run.reviewer_agent:
        raise HandoffError(
            "Escolha um revisor diferente do atual"
        )

    previous_reviewer = run.reviewer_agent
    run.reviewer_agent = new_reviewer
    run.updated_at = _now()

    event = add_run_event(
        db,
        run,
        "review.reviewer_changed",
        (
            f"Revisor trocado de {previous_reviewer or 'não definido'} para "
            f"{new_reviewer}: {reason}"
        ),
        {
            "from_reviewer": previous_reviewer,
            "to_reviewer": new_reviewer,
            "executor_agent": run.agent,
            "reason": reason,
        },
    )

    db.commit()
    db.refresh(run)
    db.refresh(event)

    return run, event


def load_reviews(db: Session, run_id) -> list[AgentRunReview]:
    """Histórico completo de revisões da execução, da mais antiga à mais nova."""
    return (
        db.query(AgentRunReview)
        .filter(AgentRunReview.run_id == run_id)
        .order_by(AgentRunReview.attempt.asc())
        .all()
    )


def record_review(
    db: Session,
    run: AgentRun,
    reviewer: str,
    verdict: str,
    feedback: str | None = None,
) -> tuple[AgentRun, AgentRunReview]:
    """Registra o veredito do revisor independente e move a execução.

    - `approved` só passa depois dos gates objetivos: a opinião do revisor não
      substitui teste, lint ou build. Gate reprovado nem chega a virar
      aprovação — vira evento de auditoria e erro.
    - `rejected` devolve a execução ao executor com o feedback escrito, sem
      apagar nada: cada rodada é uma linha nova em agent_run_reviews.
    """
    if verdict not in REVIEW_VERDICTS:
        raise HandoffError(
            "Veredito inválido; use approved ou rejected"
        )

    if run.status != "review":
        raise HandoffError(
            f"Execução em '{run.status}' não está aguardando revisão"
        )

    validate_review_pair(run.agent, reviewer)

    if run.reviewer_agent and reviewer != run.reviewer_agent:
        raise HandoffError(
            f"Revisor designado desta execução é {run.reviewer_agent}; "
            "troque o revisor pela rota de troca auditada antes de revisar"
        )

    feedback = (feedback or "").strip() or None

    if verdict == "rejected" and not feedback:
        raise HandoffError(
            "Rejeição precisa de feedback escrito para o executor corrigir"
        )

    gate_passed = None

    if verdict == "approved":
        from app.services.test_gate import validate_run_for_status_change

        gate_passed, gate_reason = validate_run_for_status_change(
            db,
            run,
            "completed",
        )

        if not gate_passed:
            add_run_event(
                db,
                run,
                "review.blocked_by_gate",
                (
                    "Aprovação do revisor não aplicada: gate objetivo "
                    f"reprovado ({gate_reason})"
                ),
                {
                    "reviewer_agent": reviewer,
                    "executor_agent": run.agent,
                    "gate_reason": gate_reason,
                },
            )
            db.commit()
            raise HandoffError(
                f"Gate objetivo reprovado: {gate_reason}. A aprovação do "
                "revisor não substitui testes, lint e build."
            )

    attempt = (run.review_attempts or 0) + 1

    review = AgentRunReview(
        run_id=run.id,
        attempt=attempt,
        executor_agent=run.agent,
        reviewer_agent=reviewer,
        verdict=verdict,
        feedback=feedback,
        gate_passed=gate_passed,
        payload={"status_before": run.status},
    )

    db.add(review)
    db.flush()

    run.review_attempts = attempt

    add_run_event(
        db,
        run,
        f"review.{verdict}",
        feedback or f"Revisão {verdict} por {reviewer}",
        {
            "attempt": attempt,
            "reviewer_agent": reviewer,
            "executor_agent": run.agent,
            "gate_passed": gate_passed,
        },
    )

    if verdict == "approved":
        run, _event = update_run(
            db,
            run,
            {
                "status": "completed",
                "result": run.result
                or f"Aprovado na revisão {attempt} por {reviewer}",
                "message": f"Revisão aprovada por {reviewer}",
            },
        )
    else:
        run, _event = update_run(
            db,
            run,
            {
                "status": "running",
                "message": (
                    f"Revisão {attempt} rejeitada por {reviewer}: {feedback}"
                ),
            },
        )

    db.refresh(review)

    return run, review


def load_subtasks(db: Session, backlog_id) -> list[BacklogSubtask]:
    """Fonte única das subtasks reais, na ordem estável de execução."""
    return (
        db.query(BacklogSubtask)
        .filter(BacklogSubtask.backlog_id == backlog_id)
        .order_by(
            BacklogSubtask.execution_order.asc(),
            BacklogSubtask.created_at.asc(),
        )
        .all()
    )


def build_context(
    db: Session,
    run: AgentRun,
) -> dict[str, Any]:
    plan = db.query(ExecutionPlan).filter(
        ExecutionPlan.id == run.plan_id
    ).first()

    task = db.query(BacklogItem).filter(
        BacklogItem.id == run.backlog_id
    ).first()

    if not plan or not task:
        raise HandoffError(
            "Plano ou task da execução não encontrado"
        )

    project = db.query(Project).filter(
        Project.id == task.project_id
    ).first()

    if not project:
        raise HandoffError(
            "Projeto da execução não encontrado"
        )

    subtasks = load_subtasks(db, run.backlog_id)

    adrs = (
        db.query(ADR)
        .filter(
            ADR.project_id == project.id,
            or_(
                ADR.feature_id == task.id,
                ADR.feature_id.is_(None),
            ),
        )
        .order_by(
            ADR.created_at.desc()
        )
        .limit(20)
        .all()
    )

    knowledge = (
        db.query(KnowledgeEntry)
        .filter(
            or_(
                KnowledgeEntry.backlog_id == task.id,
                KnowledgeEntry.project_id == project.id,
            )
        )
        .order_by(
            KnowledgeEntry.created_at.desc()
        )
        .limit(20)
        .all()
    )

    decisions = (
        db.query(Decision)
        .filter(
            Decision.project_id == project.id
        )
        .order_by(
            Decision.created_at.desc()
        )
        .limit(20)
        .all()
    )

    events = (
        db.query(AgentRunEvent)
        .filter(
            AgentRunEvent.run_id == run.id
        )
        .order_by(
            AgentRunEvent.created_at.asc()
        )
        .all()
    )

    context = {
        "runtime": AutoRuntimeConfig(
            run_id=str(run.id),
            session=f"auto-{run.agent}-{run.id}",
            timeout_seconds=max(
                60,
                min(86400, int(os.getenv("AUTO_RUNTIME_TIMEOUT_SECONDS", "14400"))),
            ),
        ).model_dump(),
        "run": {
            "id": str(run.id),
            "agent": run.agent,
            "reviewer_agent": run.reviewer_agent,
            "review_attempts": run.review_attempts or 0,
            "model": run.model,
            "reasoning_effort": run.reasoning_effort,
            "routing_mode": run.routing_mode,
            "routing_reason": run.routing_reason,
            "complexity": run.complexity,
            "complexity_score": run.complexity_score,
            "status": run.status,
            "summary": run.summary,
            "result": run.result,
            "error": run.error,
            "branch": run.branch,
            "commit_sha": run.commit_sha,
            "deployment_url": run.deployment_url,
        },
        "project": {
            "id": str(project.id),
            "name": project.name,
            "slug": project.slug,
            "description": project.description,
            "stack": project.stack,
            "github_url": project.github_url,
            "dev_branch": project.dev_branch,
            "prod_branch": project.prod_branch,
            "vps": project.vps,
        },
        "task": {
            "id": str(task.id),
            "title": task.title,
            "description": task.description,
            "type": task.type,
            "priority": task.priority,
            "status": task.status,
        },
        "plan": {
            "id": str(plan.id),
            "version": plan.version,
            "status": plan.status,
            "objective": plan.objective,
            "scope": plan.scope,
            "constraints": plan.constraints or [],
            "acceptance_criteria": (
                plan.acceptance_criteria or []
            ),
            "validation_steps": (
                plan.validation_steps or []
            ),
            "implementation_notes": (
                plan.implementation_notes
            ),
        },
        "subtasks": [
            {
                "id": str(row.id),
                "order": row.execution_order,
                "title": row.title,
                "description": row.description,
                "status": row.status,
                "result": row.result,
            }
            for row in subtasks
        ],
        "adrs": [
            {
                "id": str(row.id),
                "title": row.title,
                "context": row.context,
                "decision": row.decision,
                "consequences": row.consequences,
                "status": row.status,
            }
            for row in adrs
        ],
        "knowledge": [
            {
                "id": str(row.id),
                "title": row.title,
                "category": row.category,
                "content": row.content,
                "tags": row.tags,
            }
            for row in knowledge
        ],
        "decisions": [
            {
                "id": str(row.id),
                "title": row.title,
                "description": row.description,
            }
            for row in decisions
        ],
        "events": [
            {
                "id": str(row.id),
                "type": row.event_type,
                "message": row.message,
                "payload": row.payload,
                "created_at": (
                    row.created_at.isoformat()
                    if row.created_at
                    else None
                ),
            }
            for row in events
        ],
    }

    context["prompt"] = render_agent_prompt(context)

    return context


def _bullets(values: list[str]) -> str:
    return (
        "\n".join(
            f"- {value}"
            for value in values
        )
        or "- Não informado"
    )


def render_agent_prompt(
    context: dict[str, Any],
) -> str:
    run = context["run"]
    project = context["project"]
    task = context["task"]
    plan = context["plan"]
    subtasks = context["subtasks"]
    runtime = context["runtime"]

    subtask_text = "\n".join(
        (
            f"- [{row['status']}] "
            f"{row['order']}. {row['title']}"
        )
        for row in subtasks
    ) or "- Nenhuma subtask cadastrada"

    return f"""# WorkDev Build — execução {run['id']}

Você está no estágio BUILD. Implemente o plano aprovado sem alterar seu objetivo.
Se descobrir uma decisão arquitetural incompatível, marque a execução como bloqueada
e descreva a revisão necessária em vez de mudar o plano silenciosamente.

## Roteamento
- Executor: {run['agent']}
- Revisor independente: {run.get('reviewer_agent') or 'não informado'}
- Modelo: {run['model'] or 'não informado'}
- Esforço: {run['reasoning_effort'] or 'não informado'}
- Modo: {run['routing_mode']}
- Complexidade: {run['complexity'] or 'não classificada'}
- Score: {run['complexity_score'] if run['complexity_score'] is not None else 'não informado'}
- Motivo: {run['routing_reason'] or 'não informado'}

## Runtime AUTO
- Schema: {runtime['schema_version']}
- Sessão isolada: {runtime['session']}
- Timeout: {runtime['timeout_seconds']} segundos

## Projeto
- Nome: {project['name']} ({project['slug']})
- Stack: {project['stack'] or 'não informada'}
- Repositório: {project['github_url'] or 'não informado'}
- Branch dev: {project['dev_branch'] or 'não informada'}

## Task
- ID: {task['id']}
- Título: {task['title']}
- Descrição: {task['description'] or 'não informada'}

## Plano aprovado v{plan['version']}
Objetivo: {plan['objective']}

Escopo:
{plan['scope'] or 'Não informado'}

Restrições:
{_bullets(plan['constraints'])}

Critérios de aceite:
{_bullets(plan['acceptance_criteria'])}

Validação obrigatória:
{_bullets(plan['validation_steps'])}

Notas de implementação:
{plan['implementation_notes'] or 'Nenhuma'}

Subtasks:
{subtask_text}

## Registro da execução
Use a CLI local, que não exibe secrets:
`python3 /opt/workdev/scripts/workdev_agent.py start {run['id']}`
`python3 /opt/workdev/scripts/workdev_agent.py block {run['id']} "motivo"`
`python3 /opt/workdev/scripts/workdev_agent.py review {run['id']} "resumo"`

O revisor independente registra o veredito (e só ele):
`python3 /opt/workdev/scripts/workdev_agent.py verdict {run['id']} <revisor> approved`
`python3 /opt/workdev/scripts/workdev_agent.py verdict {run['id']} <revisor> rejected "feedback"`

Preserve alterações preexistentes, execute as validações do plano e registre o
resultado real. Não declare testes, commit ou deploy que não tenham ocorrido.

Você é o executor, não o aprovador: ao terminar, use `review` para entregar a
execução ao revisor independente. Concluir a task é decisão dele, depois dos
gates objetivos.
"""


def task_requires_deploy(db: Session, backlog_id: UUID) -> bool:
    from app.models.backlog import BacklogItem
    from app.models.project import Project

    task = db.query(BacklogItem).filter(BacklogItem.id == backlog_id).first()
    if not task:
        return False

    project = db.query(Project).filter(Project.id == task.project_id).first()
    if not project:
        return False

    # Check for explicit deployment targets in the project configuration
    return bool(
        project.vps or
        project.supabase_project or
        project.netlify_project or
        project.vercel_project
    )


def promote_pending_subtasks(db: Session, task: BacklogItem) -> None:
    subtasks = db.query(BacklogSubtask).filter(
        BacklogSubtask.backlog_id == task.id
    ).all()

    for subtask in subtasks:
        if subtask.status != "done":
            ref_marker = f"[subtask_ref: {subtask.id}]"
            # Idempotency check: search if a task with this reference marker already exists
            already_promoted = db.query(BacklogItem).filter(
                BacklogItem.description.like(f"%{ref_marker}%")
            ).first()

            if not already_promoted:
                new_task = BacklogItem(
                    project_id=task.project_id,
                    title=subtask.title,
                    description=(
                        f"Gerada automaticamente por conclusão parcial da task '{task.title}'.\n"
                        f"Origem: Subtask '{subtask.title}' da task pai '{task.title}' ({task.id}).\n\n"
                        f"{ref_marker}"
                    ),
                    type="feature",
                    priority="medium",
                    status="todo",
                    owner=None,
                    effort=None,
                    sprint=task.sprint,
                )
                db.add(new_task)
