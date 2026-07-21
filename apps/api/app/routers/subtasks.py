from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from uuid import UUID
from app.database import SessionLocal
from app.models.subtask import BacklogSubtask
from app.models.backlog import BacklogItem
from app.schemas.subtask import SubtaskCreate, SubtaskUpdate, SubtaskOut
from app.services.engineering_graph import graph_sync

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/subtasks/{backlog_id}", response_model=list[SubtaskOut])
def list_subtasks(backlog_id: UUID, db: Session = Depends(get_db)):
    return (db.query(BacklogSubtask)
            .filter(BacklogSubtask.backlog_id == backlog_id)
            .order_by(BacklogSubtask.execution_order.asc(),
                      BacklogSubtask.created_at.asc())
            .all())


@router.post("/subtasks", response_model=SubtaskOut, status_code=201)
def create_subtask(sub: SubtaskCreate, background_tasks: BackgroundTasks,
                   db: Session = Depends(get_db)):
    backlog = db.query(BacklogItem).filter(BacklogItem.id == sub.backlog_id).first()
    if not backlog:
        raise HTTPException(404, "Backlog item not found")
    obj = BacklogSubtask(**sub.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    background_tasks.add_task(
        graph_sync.sync_safely,
        "sync_subtask",
        str(obj.id),
        str(obj.backlog_id),
        str(backlog.project_id),
    )
    return obj


@router.patch("/subtasks/{subtask_id}", response_model=SubtaskOut)
def update_subtask(subtask_id: UUID, sub: SubtaskUpdate,
                   db: Session = Depends(get_db)):
    obj = db.query(BacklogSubtask).filter(BacklogSubtask.id == subtask_id).first()
    if not obj:
        raise HTTPException(404, "Subtask not found")
    for k, v in sub.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    obj.updated_at = db.execute(text("SELECT now()")).scalar()
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/subtasks/{subtask_id}", status_code=204)
def delete_subtask(subtask_id: UUID, db: Session = Depends(get_db)):
    obj = db.query(BacklogSubtask).filter(BacklogSubtask.id == subtask_id).first()
    if not obj:
        raise HTTPException(404, "Subtask not found")
    db.delete(obj)
    db.commit()
