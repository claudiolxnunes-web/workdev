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
from app.models.handoff import AgentRun, AgentRunEvent, ExecutionPlan
from app.models.knowledge import KnowledgeEntry
from app.models.project import Project
from app.models.subtask import BacklogSubtask


PLAN_EDITABLE = {"draft", "needs_revision"}
ACTIVE_RUN_STATUSES = {"queued", "running", "blocked", "review"}
TRANSFERABLE_RUN_STATUSES = {"queued", "running", "blocked"}

SUPPORTED_AGENTS = {
    "codex",
    "claude",
    "kimi",
    "qwen",
    "gemini",
}

SUPPORTED_ROUTING_MODES = {"manual", "auto"}
COMPLEXITY_LEVELS = {"low", "medium", "high", "critical"}

RUN_TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"blocked", "review", "completed", "failed", "cancelled"},
    "blocked": {"running", "cancelled", "failed"},
    "review": {"running", "blocked", "completed", "failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


class HandoffError(RuntimeError):
    pass


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
            "Agente inválido; escolha codex, claude, kimi, qwen ou gemini"
        )

    if routing_mode not in SUPPORTED_ROUTING_MODES:
        raise HandoffError(
            "routing_mode inválido; escolha manual ou auto"
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

    db.commit()
    db.refresh(plan)

    return plan


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
        f"Build enviado para {agent}",
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
                task.status = "done"
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
) -> tuple[AgentRun, AgentRun]:
    if new_agent not in SUPPORTED_AGENTS:
        raise HandoffError(
            "Agente inválido; escolha codex, claude, kimi, qwen ou gemini"
        )

    if new_agent == run.agent:
        raise HandoffError(
            "Escolha um agente diferente do atual para transferir"
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
        },
    )

    db.commit()
    db.refresh(new_run)

    return cancelled_run, new_run


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
- Agente: {run['agent']}
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
`python3 /opt/workdev/scripts/workdev_agent.py complete {run['id']} "resultado"`

Preserve alterações preexistentes, execute as validações do plano e registre o
resultado real. Não declare testes, commit ou deploy que não tenham ocorrido.
"""
