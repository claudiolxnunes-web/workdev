import os
import subprocess
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.adr import ADR
from app.models.backlog import BacklogItem
from app.models.decision import Decision
from app.models.handoff import AgentRun, AgentRunEvent, ExecutionPlan
from app.models.knowledge import KnowledgeEntry
from app.models.project import Project
from app.models.rfc import RFC
from app.models.subtask import BacklogSubtask
from app.services.engineering_graph import graph_sync

router = APIRouter(prefix="/engineering", tags=["engineering"])

SERVICES = ["workdev-api", "docker", "cron"]
BACKUP_DIR = "/opt/backups/postgres"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class GraphEvent(BaseModel):
    kind: Literal["commit", "deployment", "monitoring"]
    entity_id: str
    project_id: UUID
    parent_entity_id: str | None = None


def run(cmd: list) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    except Exception as e:
        return f"erro: {type(e).__name__}"


def servicos() -> list:
    out = []
    for s in SERVICES:
        estado = run(["systemctl", "is-active", s]) or "desconhecido"
        out.append({"nome": s, "estado": estado})
    return out


def containers() -> list:
    raw = run(["docker", "ps", "-a", "--format",
               "{{.Names}}|{{.State}}|{{.Status}}"])
    itens = []
    for linha in raw.splitlines():
        partes = linha.split("|")
        if len(partes) == 3:
            itens.append({"nome": partes[0], "estado": partes[1],
                          "status": partes[2]})
    return itens


def backups() -> list:
    itens = []
    try:
        arqs = sorted(os.listdir(BACKUP_DIR), reverse=True)[:6]
        for a in arqs:
            p = os.path.join(BACKUP_DIR, a)
            st = os.stat(p)
            itens.append({
                "arquivo": a,
                "tamanho_mb": round(st.st_size / 1048576, 2),
                "data": datetime.fromtimestamp(st.st_mtime)
                        .strftime("%d/%m %H:%M"),
            })
    except Exception as e:
        itens.append({"erro": type(e).__name__})
    return itens


def recursos() -> dict:
    disco = run(["df", "-h", "/", "--output=used,avail,pcent"])
    mem = run(["free", "-m"])
    d = {}
    linhas = disco.splitlines()
    if len(linhas) >= 2:
        c = linhas[1].split()
        if len(c) >= 3:
            d["disco"] = {"usado": c[0], "livre": c[1], "pct": c[2]}
    for linha in mem.splitlines():
        if linha.startswith("Mem"):
            c = linha.split()
            if len(c) >= 4:
                d["memoria_mb"] = {"total": c[1], "usada": c[2],
                                   "livre": c[3]}
    return d


@router.get("/status")
def status():
    return {
        "gerado_em": datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC"),
        "servicos": servicos(),
        "containers": containers(),
        "backups": backups(),
        "recursos": recursos(),
    }


@router.get("/graph/status")
def graph_status():
    return graph_sync.configuration_status()


@router.get("/graph/labels")
def graph_labels(project_id: UUID | None = None,
                 db: Session = Depends(get_db)):
    """Resolve títulos atrás da autenticação do WorkDev.

    O Supabase público armazena somente tipo e IDs; nomes de projetos e tasks
    não são expostos pela policy anônima de leitura do grafo.
    """
    labels: dict[str, str] = {}

    projects = db.query(Project)
    if project_id:
        projects = projects.filter(Project.id == project_id)
    for project in projects.all():
        labels[str(project.id)] = project.name

    backlog = db.query(BacklogItem)
    if project_id:
        backlog = backlog.filter(BacklogItem.project_id == project_id)
    items = backlog.all()
    item_ids = [item.id for item in items]
    for item in items:
        labels[str(item.id)] = item.title

    if item_ids:
        for subtask in db.query(BacklogSubtask).filter(
            BacklogSubtask.backlog_id.in_(item_ids)
        ).all():
            labels[str(subtask.id)] = subtask.title

    for model in (KnowledgeEntry, ADR, RFC, Decision):
        query = db.query(model)
        if project_id:
            query = query.filter(model.project_id == project_id)
        for row in query.all():
            labels[str(row.id)] = row.title

    plans = db.query(ExecutionPlan)
    if item_ids:
        plans = plans.filter(ExecutionPlan.backlog_id.in_(item_ids))
    elif project_id:
        plans = plans.filter(False)
    plan_rows = plans.all()
    plan_ids = [row.id for row in plan_rows]
    task_titles = {str(item.id): item.title for item in items}
    for row in plan_rows:
        labels[str(row.id)] = (
            f"Plano v{row.version} · {task_titles.get(str(row.backlog_id), 'Task')}"
        )

    runs = db.query(AgentRun)
    if plan_ids:
        runs = runs.filter(AgentRun.plan_id.in_(plan_ids))
    elif project_id:
        runs = runs.filter(False)
    run_rows = runs.all()
    run_ids = [row.id for row in run_rows]
    for row in run_rows:
        labels[str(row.id)] = f"{row.agent.title()} · {row.status}"

    events = db.query(AgentRunEvent)
    if run_ids:
        events = events.filter(AgentRunEvent.run_id.in_(run_ids))
    elif project_id:
        events = events.filter(False)
    for row in events.all():
        labels[str(row.id)] = row.event_type

    return {"labels": labels}


@router.post("/graph/events", status_code=202)
def publish_graph_event(payload: GraphEvent):
    if not graph_sync.configured:
        raise HTTPException(
            status_code=503,
            detail="Configure SUPABASE_SECRET_KEY no backend",
        )
    if payload.kind == "commit":
        node = graph_sync.sync_commit(
            payload.entity_id, payload.project_id, payload.parent_entity_id
        )
    elif payload.kind == "deployment":
        node = graph_sync.sync_deployment(
            payload.entity_id, payload.project_id, payload.parent_entity_id
        )
    else:
        node = graph_sync.sync_related(
            "Monitoring",
            payload.entity_id,
            payload.project_id,
            "RELATES_TO",
            payload.parent_entity_id,
        )
    return {"accepted": True, "node_id": node["id"]}


@router.post("/graph/sync")
def backfill_graph(db: Session = Depends(get_db)):
    if not graph_sync.configured:
        raise HTTPException(
            status_code=503,
            detail="Configure SUPABASE_SECRET_KEY no backend",
        )

    result = {"synced": 0, "failed": 0, "errors": []}

    def execute(operation: str, *args):
        try:
            getattr(graph_sync, operation)(*args)
            result["synced"] += 1
        except Exception as error:
            result["failed"] += 1
            if len(result["errors"]) < 10:
                result["errors"].append(
                    {"operation": operation, "error": str(error)[:300]}
                )

    projects = db.query(Project).all()
    for project in projects:
        execute("sync_project", str(project.id))

    backlog = db.query(BacklogItem).all()
    backlog_by_id = {item.id: item for item in backlog}
    for item in backlog:
        execute(
            "sync_backlog", str(item.id), str(item.project_id), item.type
        )

    for subtask in db.query(BacklogSubtask).all():
        parent = backlog_by_id.get(subtask.backlog_id)
        if parent:
            execute(
                "sync_subtask",
                str(subtask.id),
                str(subtask.backlog_id),
                str(parent.project_id),
            )

    related = (
        (db.query(KnowledgeEntry).all(), "Knowledge", "LINKED_TO_KNOWLEDGE"),
        (db.query(ADR).all(), "ADR", "LINKED_TO_ADR"),
        (db.query(RFC).all(), "RFC", "LINKED_TO_RFC"),
        (db.query(Decision).all(), "Decision", "HAS_DECISION"),
    )
    for rows, node_type, relationship in related:
        for row in rows:
            if row.project_id:
                execute(
                    "sync_related",
                    node_type,
                    str(row.id),
                    str(row.project_id),
                    relationship,
                    (
                        str(row.feature_id)
                        if node_type in ("ADR", "RFC") and row.feature_id
                        else str(row.backlog_id)
                        if node_type == "Knowledge" and row.backlog_id
                        else None
                    ),
                )

    plans = db.query(ExecutionPlan).all()
    for plan in plans:
        parent = backlog_by_id.get(plan.backlog_id)
        if parent:
            execute(
                "sync_plan", str(plan.id), str(parent.project_id),
                str(plan.backlog_id),
            )

    plan_by_id = {row.id: row for row in plans}
    runs = db.query(AgentRun).all()
    for run in runs:
        plan = plan_by_id.get(run.plan_id)
        parent = backlog_by_id.get(run.backlog_id)
        if plan and parent:
            execute(
                "sync_agent_run", str(run.id), str(parent.project_id),
                str(plan.id), str(run.backlog_id),
            )

    run_by_id = {row.id: row for row in runs}
    for event in db.query(AgentRunEvent).all():
        run = run_by_id.get(event.run_id)
        parent = backlog_by_id.get(run.backlog_id) if run else None
        if run and parent:
            execute(
                "sync_agent_event", str(event.id), str(parent.project_id),
                str(run.id),
            )

    return result
