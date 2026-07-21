from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from uuid import UUID
from app.database import SessionLocal
from app.models.backlog import BacklogItem
from app.models.project import Project
from app.schemas.backlog import BacklogCreate, BacklogUpdate, BacklogOut
from app.services.engineering_graph import graph_sync

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/backlog", response_model=list[BacklogOut])
def list_backlog(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(BacklogItem)
    if status:
        q = q.filter(BacklogItem.status == status)
    return q.order_by(BacklogItem.rank.asc().nulls_last(),
                      BacklogItem.created_at.asc()).all()


@router.get("/backlog/{project_slug}", response_model=list[BacklogOut])
def project_backlog(project_slug: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.slug == project_slug).first()
    if not project:
        raise HTTPException(404, "Project not found")
    return (db.query(BacklogItem)
            .filter(BacklogItem.project_id == project.id)
            .order_by(BacklogItem.rank.asc().nulls_last(),
                      BacklogItem.created_at.asc())
            .all())


@router.post("/backlog", response_model=BacklogOut, status_code=201)
def create_item(item: BacklogCreate, background_tasks: BackgroundTasks,
                db: Session = Depends(get_db)):
    if not db.query(Project).filter(Project.id == item.project_id).first():
        raise HTTPException(404, "Project not found")
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
    for k, v in item.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    obj.updated_at = db.execute(text("SELECT now()")).scalar()
    db.commit()
    db.refresh(obj)
    return obj


@router.patch("/backlog/{item_id}/status", response_model=BacklogOut)
def update_status(item_id: UUID, status: str,
                  db: Session = Depends(get_db)):
    obj = db.query(BacklogItem).filter(BacklogItem.id == item_id).first()
    if not obj:
        raise HTTPException(404, "Backlog item not found")
    obj.status = status
    obj.updated_at = db.execute(text("SELECT now()")).scalar()
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
