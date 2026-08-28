from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.backlog import BacklogItem
from app.models.handoff import AgentRun, AgentRunEvent, ExecutionPlan
from app.models.project import Project
from app.models.subtask import BacklogSubtask
from app.schemas.handoff import (
    BuildRequest,
    PlanCreate,
    PlanUpdate,
    RunEventCreate,
    RunTransfer,
    RunUpdate,
    SubtaskProgress,
)
from app.services.engineering_graph import graph_sync
from app.services.handoff import (
    HandoffError,
    add_run_event,
    approve_plan,
    build_context,
    create_plan,
    queue_build,
    transfer_run,
    update_plan,
    update_run,
)
from app.services.agent_router import (
    AgentRoutingError,
    route_agent,
)
from app.services.task_complexity import (
    classify_task,
)

from app.routers.terminal import (
    start_agent_runtime,
    stop_agent_runtime,
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


@router.post("/plans/{plan_id}/approve")
def approve_execution_plan(
    plan_id: UUID,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        plan = approve_plan(
            db,
            _get_plan(
                db,
                plan_id,
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

    if payload.routing_mode == "auto":
        task, _project = _task_project(
            db,
            plan.backlog_id,
        )

        assessment = classify_task(
            task,
            plan,
            [],
        )

        try:
            decision = route_agent(
                db,
                assessment,
                allow_premium=False,
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

    if run.routing_mode == "auto":
        context = build_context(
            db,
            run,
        )
        background.add_task(
            start_agent_runtime,
            run.agent,
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
    try:
        run, event = update_run(
            db,
            _get_run(
                db,
                run_id,
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

    _sync_run(
        background,
        db,
        run,
        event,
    )

    if (
        run.routing_mode == "auto"
        and run.status in {
            "completed",
            "failed",
            "cancelled",
        }
        and event is not None
    ):
        background.add_task(
            stop_agent_runtime,
            run.agent,
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
