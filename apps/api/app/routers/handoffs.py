from typing import Any
from uuid import UUID
import os
import threading
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.backlog import BacklogItem
from app.models.handoff import (
    AgentBuildJob,
    AgentRun,
    AgentRunEvent,
    ExecutionPlan,
)
from app.models.project import Project
from app.models.subtask import BacklogSubtask
from app.schemas.handoff import (
    BuildRequest,
    PlanCreate,
    PlanUpdate,
    ReviewerSwap,
    RunEventCreate,
    RunReviewCreate,
    RunTransfer,
    RunUpdate,
    SubtaskProgress,
)
from app.services import agent_runtimes, build_jobs
from app.services.agent_runtimes import is_ollama_agent
from app.services.build_rag import augment_prompt
from app.services.plan_granularity import assess as assess_plan_granularity
from app.services.engineering_graph import graph_sync
from app.services.ollama_driver import (
    OllamaDispatchError,
    dispatch as dispatch_to_ollama,
    ensure_dispatchable_blocking,
)
from app.services.handoff import (
    HandoffError,
    add_run_event,
    approve_plan,
    build_context,
    create_plan,
    decompose_plan,
    load_reviews,
    load_subtasks,
    queue_build,
    record_review,
    swap_reviewer,
    transfer_run,
    update_plan,
    update_run,
)
from app.services.agent_recommendation import (
    allowed_models_for_agent,
    detect_quota_blocks,
    recommend_agents,
)
from app.services.agent_router import (
    AgentRoutingError,
    route_agent,
)
from app.services.task_complexity import (
    classify_task,
)

from app.routers.terminal import (
    agent_runtime_snapshot,
    auto_runtime_running,
    finalize_auto_runtime,
    start_agent_runtime,
)

router = APIRouter(prefix="/handoffs", tags=["handoffs"])
plans_router = APIRouter(prefix="/plans", tags=["plans"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _task_project(
    db: Session,
    backlog_id,
) -> tuple[BacklogItem, Project]:
    task = db.query(BacklogItem).filter(
        BacklogItem.id == backlog_id
    ).first()

    if not task:
        raise HTTPException(
            404,
            "Task do backlog não encontrada",
        )

    project = db.query(Project).filter(
        Project.id == task.project_id
    ).first()

    if not project:
        raise HTTPException(
            404,
            "Projeto não encontrado",
        )

    return task, project


def _plan_out(
    db: Session,
    plan: ExecutionPlan,
) -> dict:
    task, project = _task_project(
        db,
        plan.backlog_id,
    )

    return {
        "id": plan.id,
        "backlog_id": plan.backlog_id,
        "version": plan.version,
        "status": plan.status,
        "title": plan.title,
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
        "created_by": plan.created_by,
        "approved_at": plan.approved_at,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "task_title": task.title,
        "project_id": project.id,
        "project_name": project.name,
    }


def _run_out(
    db: Session,
    run: AgentRun,
) -> dict:
    task, project = _task_project(
        db,
        run.backlog_id,
    )

    plan = db.query(ExecutionPlan).filter(
        ExecutionPlan.id == run.plan_id
    ).first()

    return {
        "id": run.id,
        "plan_id": run.plan_id,
        "backlog_id": run.backlog_id,
        "agent": run.agent,
        "reviewer_agent": run.reviewer_agent,
        "review_attempts": run.review_attempts or 0,
        "model": run.model,
        "reasoning_effort": run.reasoning_effort,
        "complexity": run.complexity,
        "complexity_score": run.complexity_score,
        "routing_mode": run.routing_mode,
        "routing_reason": run.routing_reason,
        "status": run.status,
        "summary": run.summary,
        "result": run.result,
        "error": run.error,
        "branch": run.branch,
        "commit_sha": run.commit_sha,
        "deployment_url": run.deployment_url,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "task_title": task.title,
        "project_id": project.id,
        "project_name": project.name,
        "plan_version": (
            plan.version
            if plan
            else None
        ),
        # Estado do despacho (fatia 2). A UI precisa disto para não oferecer
        # "despachar" a uma run que já tem job vivo — o 409 do banco continua
        # sendo a garantia, isto aqui é só para não convidar ao erro.
        "dispatch_state": run.dispatch_state or "idle",
        "dispatch_attempts": run.dispatch_attempts or 0,
        "last_dispatch_at": run.last_dispatch_at,
    }


def _get_plan(
    db: Session,
    plan_id: UUID,
) -> ExecutionPlan:
    plan = db.query(ExecutionPlan).filter(
        ExecutionPlan.id == plan_id
    ).first()

    if not plan:
        raise HTTPException(
            404,
            "Plano não encontrado",
        )

    return plan


def _get_run(
    db: Session,
    run_id: UUID,
) -> AgentRun:
    run = db.query(AgentRun).filter(
        AgentRun.id == run_id
    ).first()

    if not run:
        raise HTTPException(
            404,
            "Execução não encontrada",
        )

    return run


def _sync_plan(
    background: BackgroundTasks,
    db: Session,
    plan: ExecutionPlan,
):
    task, project = _task_project(
        db,
        plan.backlog_id,
    )

    background.add_task(
        graph_sync.sync_safely,
        "sync_plan",
        str(plan.id),
        str(project.id),
        str(task.id),
    )


def _sync_run(
    background: BackgroundTasks,
    db: Session,
    run: AgentRun,
    event: AgentRunEvent | None = None,
):
    task, project = _task_project(
        db,
        run.backlog_id,
    )

    background.add_task(
        graph_sync.sync_safely,
        "sync_agent_run",
        str(run.id),
        str(project.id),
        str(run.plan_id),
        str(task.id),
    )

    if event:
        background.add_task(
            graph_sync.sync_safely,
            "sync_agent_event",
            str(event.id),
            str(project.id),
            str(run.id),
        )


def _sync_auto_transition(
    db: Session,
    run: AgentRun,
    event: AgentRunEvent | None,
) -> None:
    task, project = _task_project(db, run.backlog_id)
    graph_sync.sync_safely(
        "sync_agent_run",
        str(run.id),
        str(project.id),
        str(run.plan_id),
        str(task.id),
    )
    if event:
        graph_sync.sync_safely(
            "sync_agent_event",
            str(event.id),
            str(project.id),
            str(run.id),
        )


def _monitor_auto_agent(run_id: UUID, agent: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(5)
        db = SessionLocal()
        try:
            run = _get_run(db, run_id)
            if run.status in {"completed", "failed", "cancelled"}:
                return
            if run.status != "running":
                continue
            if auto_runtime_running(agent, run_id):
                continue
            finalize_auto_runtime(agent, run_id)
            run, event = update_run(db, run, {
                "status": "failed",
                "error": "Runtime AUTO encerrou antes de registrar resultado",
                "message": "Runtime AUTO desapareceu; sessão limpa e agente em standby",
            })
            _sync_auto_transition(db, run, event)
            return
        finally:
            db.close()

    db = SessionLocal()
    try:
        run = _get_run(db, run_id)
        if run.status == "running":
            finalize_auto_runtime(agent, run_id)
            run, event = update_run(db, run, {
                "status": "failed",
                "error": f"Timeout de segurança após {timeout_seconds} segundos",
                "message": "Runtime AUTO excedeu o timeout; sessão limpa e agente em standby",
            })
            _sync_auto_transition(db, run, event)
    finally:
        db.close()


def _start_auto_monitor(run_id: UUID, agent: str) -> None:
    timeout_seconds = max(
        60,
        min(86400, int(os.getenv("AUTO_RUNTIME_TIMEOUT_SECONDS", "14400"))),
    )
    threading.Thread(
        target=_monitor_auto_agent,
        args=(run_id, agent, timeout_seconds),
        name=f"auto-monitor-{run_id}",
        daemon=True,
    ).start()


def _run_auto_agent(
    run_id: UUID,
    agent: str,
    model: str | None,
    prompt: str,
) -> None:
    db = SessionLocal()
    try:
        run = _get_run(db, run_id)
        if run.routing_mode != "auto" or run.status != "queued":
            return

        run, event = update_run(
            db,
            run,
            {
                "status": "running",
                "message": f"Runtime AUTO iniciou {agent}",
            },
        )
        _sync_auto_transition(db, run, event)

        try:
            start_agent_runtime(agent, prompt, model=model, run_id=run_id)
        except Exception as error:
            db.rollback()
            db.expire_all()
            run = _get_run(db, run_id)
            if run.status == "running":
                try:
                    finalize_auto_runtime(agent, run_id)
                    terminal_status = "failed"
                    terminal_error = str(error)
                except Exception as cleanup_error:
                    terminal_status = "blocked"
                    terminal_error = (
                        f"{error}; cleanup pendente: {cleanup_error}"
                    )
                run, event = update_run(
                    db,
                    run,
                    {
                        "status": terminal_status,
                        "error": terminal_error,
                        "message": f"Runtime AUTO falhou: {terminal_error}",
                    },
                )
                _sync_auto_transition(db, run, event)
            return

        if agent != "gemini":
            _start_auto_monitor(run_id, agent)
            return

        # GEMINI AUTO: fluxo correto para conclusão
        # 1. Execução técnica terminou (runtime headless encerrou)
        # 2. Executar gate ANTES de marcar completed
        # 3. Persistir evidência
        # 4. Se gate PASS: avançar para completed
        # 5. Se gate FAIL: ir para blocked/review com justificativa
        # 6. Só então finalizar runtime

        db.expire_all()
        run = _get_run(db, run_id)

        if run.status == "running":
            # Executar gate antes de qualquer transição terminal
            from app.services.test_gate import execute_gate, persist_gate_evidence

            gate_evidence = execute_gate(run)
            gate_event = persist_gate_evidence(db, gate_evidence)

            # Decidir status baseado no gate
            if gate_evidence.passed:
                # Gate PASS: entrega ao revisor independente. Execução técnica
                # terminada nunca é conclusão — quem conclui é a revisão.
                reviewer = getattr(run, "reviewer_agent", None)
                run, event = update_run(
                    db,
                    run,
                    {
                        "status": "review",
                        "summary": f"{agent} headless encerrou com sucesso",
                        "message": (
                            "Runtime AUTO concluiu a execução; aguardando "
                            f"revisão de {reviewer or 'revisor designado'}"
                        ),
                    },
                )
                finalize_auto_runtime(agent, run_id)
            else:
                # Gate FAIL: não completar, ir para blocked ou review
                # Para Fase 1: vai para blocked com erro do gate
                failed_checks = ", ".join(gate_evidence.mandatory_failed)
                run, event = update_run(
                    db,
                    run,
                    {
                        "status": "blocked",
                        "error": f"Gate de testes reprovado: {failed_checks}",
                        "message": "Runtime AUTO encerrou, mas testes falharam; task bloqueada para revisão",
                    },
                )
                finalize_auto_runtime(agent, run_id)

            _sync_auto_transition(db, run, event)
    finally:
        db.close()


@router.get("/plans")
def list_plans(
    status: str | None = None,
    backlog_id: UUID | None = None,
    limit: int = Query(
        50,
        ge=1,
        le=200,
    ),
    db: Session = Depends(get_db),
):
    query = db.query(ExecutionPlan)

    if status:
        query = query.filter(
            ExecutionPlan.status == status
        )
    else:
        query = query.filter(
            ExecutionPlan.status != "discarded"
        )

    if backlog_id:
        query = query.filter(
            ExecutionPlan.backlog_id
            == backlog_id
        )

    rows = (
        query
        .order_by(
            ExecutionPlan.created_at.desc()
        )
        .limit(limit)
        .all()
    )

    return [
        _plan_out(db, row)
        for row in rows
    ]


@router.post(
    "/plans",
    status_code=201,
)
def create_execution_plan(
    payload: PlanCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        plan = create_plan(
            db,
            payload.model_dump(),
        )
    except HandoffError as error:
        raise HTTPException(
            400,
            str(error),
        ) from error

    _sync_plan(
        background,
        db,
        plan,
    )

    return _plan_out(
        db,
        plan,
    )


@router.get("/plans/{plan_id}")
def get_execution_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
):
    return _plan_out(
        db,
        _get_plan(
            db,
            plan_id,
        ),
    )


@plans_router.patch("/{plan_id}")
@router.patch("/plans/{plan_id}")
def edit_execution_plan(
    plan_id: UUID,
    payload: PlanUpdate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        plan = update_plan(
            db,
            _get_plan(
                db,
                plan_id,
            ),
            payload.model_dump(
                exclude_unset=True,
            ),
        )
    except HandoffError as error:
        raise HTTPException(
            409,
            str(error),
        ) from error

    _sync_plan(
        background,
        db,
        plan,
    )

    return _plan_out(
        db,
        plan,
    )


@router.get("/plans/{plan_id}/granularity")
def get_plan_granularity(
    plan_id: UUID,
    db: Session = Depends(get_db),
):
    """Diagnóstico de tamanho do plano e fatias sugeridas. Não altera nada."""
    plan = _get_plan(db, plan_id)

    payload = assess_plan_granularity(
        plan,
        load_subtasks(db, plan.backlog_id),
    )
    payload["plan_id"] = str(plan.id)
    payload["plan_version"] = plan.version

    return payload


@router.post(
    "/plans/{plan_id}/decompose",
    status_code=201,
)
def decompose_execution_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
):
    """Cria as fatias sugeridas como subtasks auditáveis da task."""
    plan = _get_plan(db, plan_id)

    try:
        criadas = decompose_plan(db, plan)
    except HandoffError as error:
        raise HTTPException(409, str(error)) from error

    return {
        "plan_id": plan.id,
        "created": [
            {
                "id": row.id,
                "order": row.execution_order,
                "title": row.title,
            }
            for row in criadas
        ],
        "subtasks": [
            {
                "id": row.id,
                "order": row.execution_order,
                "title": row.title,
                "status": row.status,
            }
            for row in load_subtasks(db, plan.backlog_id)
        ],
    }


@router.post("/plans/{plan_id}/approve")
def approve_execution_plan(
    plan_id: UUID,
    background: BackgroundTasks,
    force: bool = Query(
        False,
        description=(
            "Aprova mesmo com o plano acima do tamanho de uma unidade "
            "auditável, assumindo a exceção"
        ),
    ),
    db: Session = Depends(get_db),
):
    try:
        plan = approve_plan(
            db,
            _get_plan(
                db,
                plan_id,
            ),
            allow_oversized=force,
        )
    except HandoffError as error:
        raise HTTPException(
            409,
            str(error),
        ) from error

    _sync_plan(
        background,
        db,
        plan,
    )

    return _plan_out(
        db,
        plan,
    )


_AUTO_RUNTIME_FLAG = "WORKDEV_AUTO_RUNTIME_ENABLED"


def _auto_runtime_enabled() -> bool:
    """O tmux é terminal persistente manual, não orquestrador do AUTO.

    O caminho principal é PLAN → recomendação → escolha do usuário → envio ao
    agente escolhido, que trabalha na sua própria sessão persistente. O runtime
    AUTO com sessão dinâmica `auto-<agent>-<run_id>` continua existindo no
    backend, mas só liga sob opt-in explícito. Desligado, um build AUTO ainda
    classifica, roteia e enfileira a execução — o agente a recolhe pela CLI, na
    sua sessão de sempre, sem criação dinâmica de runtime.
    """
    return os.getenv(_AUTO_RUNTIME_FLAG, "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


_RUNTIME_SNAPSHOT_TTL_SECONDS = 5
_runtime_snapshot_cache: dict[str, Any] = {"at": 0.0, "value": None}
_runtime_snapshot_lock = threading.Lock()


def _cached_runtime_snapshot() -> dict[str, dict]:
    """Evita varrer o tmux uma vez por plano renderizado na aba de PLAN."""
    with _runtime_snapshot_lock:
        now = time.monotonic()
        cached = _runtime_snapshot_cache["value"]

        if (
            cached is not None
            and now - _runtime_snapshot_cache["at"]
            < _RUNTIME_SNAPSHOT_TTL_SECONDS
        ):
            return cached

    snapshot = agent_runtime_snapshot()

    with _runtime_snapshot_lock:
        _runtime_snapshot_cache["at"] = time.monotonic()
        _runtime_snapshot_cache["value"] = snapshot

    return snapshot


@router.get("/plans/{plan_id}/recommendation")
def get_plan_recommendation(
    plan_id: UUID,
    db: Session = Depends(get_db),
):
    """Recomendação consultiva de agente/modelo. Não inicia nada."""
    plan = _get_plan(
        db,
        plan_id,
    )

    task, _project = _task_project(
        db,
        plan.backlog_id,
    )

    subtasks = load_subtasks(
        db,
        plan.backlog_id,
    )

    payload = recommend_agents(
        db,
        task,
        plan,
        subtasks,
        runtime=_cached_runtime_snapshot(),
        quota_signals=detect_quota_blocks(db),
    )

    payload["plan_id"] = str(plan.id)
    payload["plan_version"] = plan.version

    return payload


def execute_test_gate_for_run(db: Session, run: AgentRun) -> dict:
    """
    Executar gate de testes para um AgentRun e persistir evidência.

    Usa o service dedicado test_gate para execução e persistência.
    Retorna resultado para o caller.
    """
    from app.services.test_gate import execute_gate, persist_gate_evidence

    # Executar gate
    evidence = execute_gate(run)

    # Persistir evidência como evento
    event = persist_gate_evidence(db, evidence)

    return {
        "passed": evidence.passed,
        "reason": evidence.error or "Gate aprovado",
        "evidence_id": event.id,
        "checks": [c.name for c in evidence.checks],
        "mandatory_failed": evidence.mandatory_failed,
    }


@router.post(
    "/plans/{plan_id}/build",
    status_code=201,
)
def send_to_build(
    plan_id: UUID,
    payload: BuildRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    plan = _get_plan(
        db,
        plan_id,
    )

    agent = payload.agent
    model = payload.model
    reasoning_effort = (
        payload.reasoning_effort
    )
    complexity = None
    complexity_score = None
    routing_reason = (
        "Seleção manual pelo usuário"
    )

    if payload.routing_mode == "manual" and model:
        # O usuário escolhe o modelo, mas só entre os permitidos do agente.
        # O catálogo inteiro nunca é opção de envio.
        allowed = allowed_models_for_agent(db, agent)

        if allowed and model not in {
            row.provider_model_id for row in allowed
        }:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "model_not_allowed_for_agent",
                    "message": (
                        f"O modelo {model} não está configurado para "
                        f"{agent}."
                    ),
                    "details": {
                        "agent": agent,
                        "allowed_models": [
                            {
                                "model": row.provider_model_id,
                                "model_label": row.display_name,
                            }
                            for row in allowed
                        ],
                    },
                },
            )

    if payload.routing_mode == "manual" and is_ollama_agent(agent):
        # Endpoint indisponível não vira run pendurada: recusa antes de criar
        # qualquer estado. Os demais agentes seguem utilizáveis normalmente.
        try:
            ensure_dispatchable_blocking(agent)
        except OllamaDispatchError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                },
            ) from error

    if payload.routing_mode == "auto":
        task, _project = _task_project(
            db,
            plan.backlog_id,
        )

        subtasks = load_subtasks(db, plan.backlog_id)

        assessment = classify_task(
            task,
            plan,
            subtasks,
        )

        try:
            decision = route_agent(
                db,
                assessment,
                allow_premium=payload.premium_confirmed,
            )
        except AgentRoutingError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                },
            ) from error

        agent = decision.agent
        model = decision.model
        reasoning_effort = (
            decision.reasoning_effort
        )
        complexity = (
            decision.complexity
        )
        complexity_score = (
            decision.complexity_score
        )
        routing_reason = (
            decision.reason
        )

    try:
        run, event = queue_build(
            db,
            plan,
            agent,
            reviewer=payload.reviewer,
            model=model,
            reasoning_effort=(
                reasoning_effort
            ),
            routing_mode=(
                payload.routing_mode
            ),
            complexity=complexity,
            complexity_score=(
                complexity_score
            ),
            routing_reason=(
                routing_reason
            ),
        )
    except HandoffError as error:
        raise HTTPException(
            409,
            str(error),
        ) from error

    _sync_run(
        background,
        db,
        run,
        event,
    )

    if (
        run.routing_mode == "auto"
        and _auto_runtime_enabled()
    ):
        context = build_context(
            db,
            run,
        )
        background.add_task(
            _run_auto_agent,
            run.id,
            run.agent,
            run.model,
            context["prompt"],
        )

    return _run_out(
        db,
        run,
    )

@router.get("/runs")
def list_runs(
    agent: str | None = None,
    status: str | None = None,
    limit: int = Query(
        50,
        ge=1,
        le=200,
    ),
    db: Session = Depends(get_db),
):
    query = db.query(AgentRun)

    if agent:
        query = query.filter(
            AgentRun.agent == agent
        )

    if status:
        query = query.filter(
            AgentRun.status == status
        )

    rows = (
        query
        .order_by(
            AgentRun.created_at.desc()
        )
        .limit(limit)
        .all()
    )

    return [
        _run_out(db, row)
        for row in rows
    ]


@router.get("/runs/{run_id}")
def get_agent_run(
    run_id: UUID,
    db: Session = Depends(get_db),
):
    return _run_out(
        db,
        _get_run(
            db,
            run_id,
        ),
    )


@router.get("/runs/{run_id}/context")
def get_agent_context(
    run_id: UUID,
    db: Session = Depends(get_db),
):
    try:
        return build_context(
            db,
            _get_run(
                db,
                run_id,
            ),
        )
    except HandoffError as error:
        raise HTTPException(
            409,
            str(error),
        ) from error


@router.patch("/runs/{run_id}")
def update_agent_run(
    run_id: UUID,
    payload: RunUpdate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    current = _get_run(db, run_id)
    data = payload.model_dump(exclude_unset=True)
    requested_status = data.get("status")

    # BUG FIX: Capturar previous_status ANTES de update_run modificar o objeto
    # Após update_run, current.status já foi alterado, então a comparação
    # requested_status != current.status estaria errada
    previous_status = current.status

    # ORDEM CORRETA PARA AUTO RUNTIME:
    # 1. Validar transição (inclui gate se necessário)
    # 2. Só então finalizar runtime se transição for aceita
    # 3. Executar update_run

    # Primeiro validar transição (gate é verificado dentro de update_run)
    try:
        # Validar pré-requisitos antes de qualquer modificação
        if (
            current.routing_mode == "auto"
            and requested_status == "completed"
            and not data.get("result")
        ):
            raise HTTPException(
                409,
                "Execução AUTO concluída exige resultado persistido",
            )

        # Executar gate de testes se necessário (dentro de update_run)
        # Se gate falhar, HandoffError será lançado
        run, event = update_run(
            db,
            current,
            data,
        )

        # Só após update_run aceitar a transição, finalizar runtime
        # Usar previous_status capturado antes, não current.status que foi modificado
        if (
            current.routing_mode == "auto"
            and requested_status in {"completed", "failed", "cancelled"}
            and requested_status != previous_status
        ):
            try:
                finalize_auto_runtime(current.agent, current.id)
            except Exception as error:
                # Runtime já foi finalizado, mas transição foi aceita
                # Logar erro mas não reverter
                import logging
                logging.warning(
                    f"Runtime AUTO finalizado com erro após transição aceita: {error}"
                )

    except HandoffError as error:
        raise HTTPException(
            409,
            str(error),
        ) from error

    _sync_run(
        background,
        db,
        run,
        event,
    )

    return _run_out(
        db,
        run,
    )


@router.post(
    "/runs/{run_id}/transfer",
    status_code=201,
)
def transfer_agent_run(
    run_id: UUID,
    payload: RunTransfer,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        cancelled_run, new_run = transfer_run(
            db,
            _get_run(
                db,
                run_id,
            ),
            payload.agent,
            payload.reason,
            new_reviewer=payload.reviewer,
        )
    except HandoffError as error:
        raise HTTPException(
            409,
            str(error),
        ) from error

    _sync_run(
        background,
        db,
        cancelled_run,
    )

    _sync_run(
        background,
        db,
        new_run,
    )

    return _run_out(
        db,
        new_run,
    )


async def _consume_dispatch_job(
    run_id: UUID,
    job_id: UUID,
    prompt: str,
    model: str | None,
) -> None:
    """Consome um job de despacho fora do ciclo da requisição.

    Provisório e assim declarado: o consumidor definitivo é o worker isolado da
    fatia 3, em processo e systemd próprios, com permissão de escrever arquivo.
    Este aqui só tira a inferência de dentro da rota — que era o achado 6, a
    sessão de banco presa por até 900s — e mantém o comportamento de hoje:
    o runtime devolve TEXTO, que vira evento auditável. Nenhum arquivo é
    editado, nenhum gate roda, nada é commitado.

    A sessão é própria e curta: abre, marca `running`, solta o banco durante a
    inferência e reabre para gravar. Segurar a sessão pelo await seria repetir
    o problema que a fatia 2 existe para resolver.
    """
    db = SessionLocal()
    try:
        job = db.query(AgentBuildJob).filter(AgentBuildJob.id == job_id).first()
        if job is None or job.state != "queued":
            return
        build_jobs.start_job(db, job)
        db.commit()
        runtime_id = job.runtime_id
    finally:
        db.close()

    erro: OllamaDispatchError | None = None
    result: dict | None = None

    try:
        result = await dispatch_to_ollama(runtime_id, prompt, model=model)
    except OllamaDispatchError as falha:
        erro = falha

    db = SessionLocal()
    try:
        job = db.query(AgentBuildJob).filter(AgentBuildJob.id == job_id).first()
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()

        if job is None or run is None:  # pragma: no cover - run apagada no meio
            return

        if erro is not None:
            event = add_run_event(
                db,
                run,
                "build.dispatch_failed",
                erro.message,
                {"code": erro.code, "job_id": str(job.id), **erro.details},
            )
            build_jobs.fail_job(
                db,
                job,
                error=erro.message,
                payload={"code": erro.code, **erro.details},
            )
            db.commit()
            _sync_auto_transition(db, run, event)
            return

        if result is None:  # pragma: no cover - sem resposta e sem erro
            build_jobs.fail_job(
                db,
                job,
                error="Driver não devolveu resposta nem erro",
            )
            db.commit()
            return

        if run.status == "queued":
            run, _event = update_run(
                db,
                run,
                {
                    "status": "running",
                    "message": f"Despacho para {run.agent} iniciado",
                },
            )

        event = add_run_event(
            db,
            run,
            "build.ollama_response",
            f"Resposta de {result['runtime_id']} ({result['model']})",
            {
                "runtime_id": result["runtime_id"],
                "model": result["model"],
                "duration_ms": result["duration_ms"],
                "truncated": result["truncated"],
                "response": result["response"],
                # Guardado para auditoria: sem isto, num modelo com raciocínio
                # explícito o evento não registra nada do que ele produziu.
                "thinking": result.get("thinking") or "",
                "job_id": str(job.id),
            },
        )
        build_jobs.finish_job(
            db,
            job,
            payload={
                "duration_ms": result["duration_ms"],
                "truncated": result["truncated"],
                "event_id": str(event.id),
            },
        )
        db.commit()
        _sync_auto_transition(db, run, event)
    finally:
        db.close()


@router.post(
    "/runs/{run_id}/dispatch",
    status_code=202,
)
def dispatch_run_to_ollama(
    run_id: UUID,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Abre um job de despacho para o runtime Ollama e devolve 202.

    A rota não espera a inferência. Ela valida, registra a intenção como linha
    em `agent_build_jobs` e sai — a resposta é o `job_id`, que a UI acompanha
    por `GET /runs/{id}/dispatch/{job_id}`.

    Chamada concorrente para a mesma run devolve 409 com o `job_id` que já está
    vivo, e a recusa vem do índice parcial do banco, não de um `if` daqui.
    """
    run = _get_run(db, run_id)

    if not is_ollama_agent(run.agent):
        raise HTTPException(
            409,
            f"{run.agent} não é um runtime Ollama; use a sessão do agente",
        )

    if run.status not in {"queued", "running"}:
        raise HTTPException(
            409,
            f"Execução em '{run.status}' não aceita despacho",
        )

    # Modelo e saúde resolvidos ANTES de abrir o job: erro de configuração
    # aparece no envio, não numa linha órfã em `queued` que ninguém consome.
    try:
        runtime = ensure_dispatchable_blocking(run.agent)
    except OllamaDispatchError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "code": error.code,
                "message": error.message,
                "details": error.details,
            },
        ) from error

    model = run.model or agent_runtimes.model_for(runtime)

    if not model:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "model_not_configured",
                "message": (
                    f"Nenhum modelo configurado para {runtime.label}; defina "
                    f"{runtime.model_env}"
                ),
                "details": {"runtime_id": runtime.id},
            },
        )

    try:
        context = build_context(db, run)
    except HandoffError as error:
        raise HTTPException(409, str(error)) from error

    # O prompt sai daqui com os trechos recuperados já embutidos em texto: a
    # recuperação acontece na VPS, o runtime só lê.
    prompt = augment_prompt(context)

    try:
        job = build_jobs.open_job(
            db,
            run,
            runtime_id=run.agent,
            model=model,
            prompt_sha256=build_jobs.prompt_fingerprint(prompt),
        )
    except build_jobs.DispatchConflict as conflito:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "dispatch_already_active",
                "message": (
                    "Já existe um despacho ativo para esta execução"
                ),
                "details": build_jobs.job_out(conflito.job),
            },
        ) from conflito

    event = add_run_event(
        db,
        run,
        "build.dispatch_requested",
        f"Despacho pedido para {runtime.label} ({model})",
        {
            "job_id": str(job.id),
            "runtime_id": run.agent,
            "model": model,
            "attempt": job.attempt,
            "prompt_sha256": job.prompt_sha256,
        },
    )
    db.commit()
    db.refresh(job)

    _sync_run(background, db, run, event)
    background.add_task(_consume_dispatch_job, run.id, job.id, prompt, model)

    return {
        "run": _run_out(db, run),
        "dispatch": build_jobs.job_out(job),
    }


@router.get("/runs/{run_id}/dispatch/{job_id}")
def get_dispatch_job(
    run_id: UUID,
    job_id: UUID,
    db: Session = Depends(get_db),
):
    """Estado de um job de despacho, para a UI acompanhar sem repetir o POST."""
    job = build_jobs.get_job(db, run_id, job_id)

    if job is None:
        raise HTTPException(404, "Despacho não encontrado para esta execução")

    return build_jobs.job_out(job)


@router.post("/runs/{run_id}/reviewer")
def swap_run_reviewer(
    run_id: UUID,
    payload: ReviewerSwap,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Troca auditada do revisor, sem cancelar a execução em andamento."""
    try:
        run, event = swap_reviewer(
            db,
            _get_run(db, run_id),
            payload.reviewer,
            payload.reason,
        )
    except HandoffError as error:
        raise HTTPException(
            409,
            str(error),
        ) from error

    _sync_run(
        background,
        db,
        run,
        event,
    )

    return _run_out(db, run)


def _review_out(review) -> dict:
    return {
        "id": review.id,
        "run_id": review.run_id,
        "attempt": review.attempt,
        "executor_agent": review.executor_agent,
        "reviewer_agent": review.reviewer_agent,
        "verdict": review.verdict,
        "feedback": review.feedback,
        "gate_passed": review.gate_passed,
        "created_at": review.created_at,
    }


@router.get("/runs/{run_id}/reviews")
def list_run_reviews(
    run_id: UUID,
    db: Session = Depends(get_db),
):
    """Trilha cumulativa: toda rodada de revisão fica, mesmo as rejeitadas."""
    run = _get_run(db, run_id)

    return {
        "run_id": run.id,
        "executor_agent": run.agent,
        "reviewer_agent": run.reviewer_agent,
        "review_attempts": run.review_attempts or 0,
        "reviews": [
            _review_out(review)
            for review in load_reviews(db, run.id)
        ],
    }


@router.post(
    "/runs/{run_id}/reviews",
    status_code=201,
)
def create_run_review(
    run_id: UUID,
    payload: RunReviewCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Veredito do revisor independente sobre uma execução em revisão."""
    run = _get_run(db, run_id)

    try:
        run, review = record_review(
            db,
            run,
            payload.reviewer,
            payload.verdict,
            payload.feedback,
        )
    except HandoffError as error:
        raise HTTPException(
            409,
            str(error),
        ) from error

    _sync_run(
        background,
        db,
        run,
    )

    return {
        "review": _review_out(review),
        "run": _run_out(db, run),
    }


@router.post(
    "/runs/{run_id}/events",
    status_code=201,
)
def create_run_event(
    run_id: UUID,
    payload: RunEventCreate,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    run = _get_run(
        db,
        run_id,
    )

    event = add_run_event(
        db,
        run,
        payload.event_type,
        payload.message,
        payload.payload,
    )
    db.commit()
    db.refresh(event)

    _sync_run(
        background,
        db,
        run,
        event,
    )

    return {
        "id": event.id,
        "run_id": event.run_id,
        "event_type": event.event_type,
        "message": event.message,
        "payload": event.payload,
        "created_at": event.created_at,
    }


@router.patch(
    "/runs/{run_id}/subtasks/{subtask_id}"
)
def update_run_subtask(
    run_id: UUID,
    subtask_id: UUID,
    payload: SubtaskProgress,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    run = _get_run(
        db,
        run_id,
    )

    subtask = db.query(
        BacklogSubtask
    ).filter(
        BacklogSubtask.id == subtask_id,
        BacklogSubtask.backlog_id
        == run.backlog_id,
    ).first()

    if not subtask:
        raise HTTPException(
            404,
            "Subtask não encontrada nesta execução",
        )

    subtask.status = payload.status
    subtask.result = payload.result
    subtask.assigned_agent = run.agent

    event = add_run_event(
        db,
        run,
        "subtask.updated",
        (
            f"{subtask.title}: "
            f"{payload.status}"
        ),
        {
            "subtask_id": str(subtask.id),
            "status": payload.status,
        },
    )

    db.commit()
    db.refresh(subtask)
    db.refresh(event)

    _sync_run(
        background,
        db,
        run,
        event,
    )

    return {
        "id": subtask.id,
        "title": subtask.title,
        "status": subtask.status,
        "result": subtask.result,
        "assigned_agent": (
            subtask.assigned_agent
        ),
    }
