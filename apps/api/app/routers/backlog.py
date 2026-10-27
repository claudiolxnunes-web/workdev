from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from uuid import UUID
from app.database import SessionLocal
from app.models.backlog import BacklogItem
from app.models.project import Project
from app.schemas.backlog import BacklogCreate, BacklogUpdate, BacklogOut
from app.services.backlog_status import (
    BacklogStatusError, apply_status, validate_status,
)
from app.services.engineering_graph import graph_sync

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _status_error(error: BacklogStatusError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.as_detail())


@router.get("/backlog", response_model=list[BacklogOut])
def list_backlog(status: str | None = None, include_archived: bool = False,
                 db: Session = Depends(get_db)):
    q = db.query(BacklogItem)
    if status:
        q = q.filter(BacklogItem.status == status)
    elif not include_archived:
        # Arquivadas só saem com pedido explícito (ADR 009).
        q = q.filter(BacklogItem.status != "archived")
    return q.order_by(BacklogItem.rank.asc().nulls_last(),
                      BacklogItem.created_at.asc()).all()


@router.get("/backlog/{project_slug}", response_model=list[BacklogOut])
def project_backlog(project_slug: str, include_archived: bool = False,
                    db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.slug == project_slug).first()
    if not project:
        raise HTTPException(404, "Project not found")
    q = db.query(BacklogItem).filter(BacklogItem.project_id == project.id)
    if not include_archived:
        q = q.filter(BacklogItem.status != "archived")
    return (q.order_by(BacklogItem.rank.asc().nulls_last(),
                      BacklogItem.created_at.asc())
            .all())


@router.post("/backlog", response_model=BacklogOut, status_code=201)
def create_item(item: BacklogCreate, background_tasks: BackgroundTasks,
                db: Session = Depends(get_db)):
    if not db.query(Project).filter(Project.id == item.project_id).first():
        raise HTTPException(404, "Project not found")
    try:
        validate_status(item.status)
    except BacklogStatusError as error:
        raise _status_error(error) from error
    if item.status == "archived":
        raise HTTPException(422, detail={
            "code": "cannot_create_archived",
            "message": "Task nova não nasce arquivada; crie e depois arquive com motivo.",
            "details": {"status": item.status},
        })
    obj = BacklogItem(**item.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    background_tasks.add_task(
        graph_sync.sync_safely,
        "sync_backlog",
        str(obj.id),
        str(obj.project_id),
        obj.type,
    )
    return obj


@router.patch("/backlog/{item_id}", response_model=BacklogOut)
def update_item(item_id: UUID, item: BacklogUpdate,
                db: Session = Depends(get_db)):
    obj = db.query(BacklogItem).filter(BacklogItem.id == item_id).first()
    if not obj:
        raise HTTPException(404, "Backlog item not found")

    changes = item.model_dump(exclude_unset=True)
    status_requested = "status" in changes
    new_status = changes.pop("status", None)
    reason = changes.pop("archived_reason", None)
    note = changes.pop("archived_note", None)
    if (reason is not None or note) and not status_requested:
        raise HTTPException(422, detail={
            "code": "archived_reason_without_archive",
            "message": "Motivo de arquivamento só é aceito com status archived.",
            "details": {"status": None},
        })
    if status_requested:
        try:
            validate_status(new_status)
        except BacklogStatusError as error:
            raise _status_error(error) from error

    if item.status == "done" and obj.status != "done":
        from app.models.subtask import BacklogSubtask
        pending_subtasks = db.query(BacklogSubtask).filter(
            BacklogSubtask.backlog_id == item_id,
            BacklogSubtask.status != "done"
        ).all()
        if pending_subtasks:
            active_titles = [s.title for s in pending_subtasks]
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "active_subtasks_remaining",
                    "message": f"Não é possível concluir a tarefa pois existem {len(pending_subtasks)} subtasks pendentes: {', '.join(active_titles)}.",
                    "details": {
                        "pending_subtasks": active_titles
                    }
                }
            )

    now = db.execute(text("SELECT now()")).scalar()
    if status_requested:
        try:
            apply_status(obj, new_status, now, reason, note)
        except BacklogStatusError as error:
            raise _status_error(error) from error
    for k, v in changes.items():
        setattr(obj, k, v)
    obj.updated_at = now
    db.commit()
    db.refresh(obj)
    return obj


@router.patch("/backlog/{item_id}/status", response_model=BacklogOut)
def update_status(item_id: UUID, status: str, reason: str | None = None,
                  note: str | None = None, db: Session = Depends(get_db)):
    obj = db.query(BacklogItem).filter(BacklogItem.id == item_id).first()
    if not obj:
        raise HTTPException(404, "Backlog item not found")
    try:
        validate_status(status)
    except BacklogStatusError as error:
        raise _status_error(error) from error

    if status == "done" and obj.status != "done":
        from app.models.subtask import BacklogSubtask
        pending_subtasks = db.query(BacklogSubtask).filter(
            BacklogSubtask.backlog_id == item_id,
            BacklogSubtask.status != "done"
        ).all()
        if pending_subtasks:
            active_titles = [s.title for s in pending_subtasks]
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "active_subtasks_remaining",
                    "message": f"Não é possível concluir a tarefa pois existem {len(pending_subtasks)} subtasks pendentes: {', '.join(active_titles)}.",
                    "details": {
                        "pending_subtasks": active_titles
                    }
                }
            )

    now = db.execute(text("SELECT now()")).scalar()
    try:
        apply_status(obj, status, now, reason, note)
    except BacklogStatusError as error:
        raise _status_error(error) from error
    obj.updated_at = now
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/backlog/{item_id}", status_code=204)
def delete_item(item_id: UUID, db: Session = Depends(get_db)):
    obj = db.query(BacklogItem).filter(BacklogItem.id == item_id).first()
    if not obj:
        raise HTTPException(404, "Backlog item not found")
    db.delete(obj)
    db.commit()
