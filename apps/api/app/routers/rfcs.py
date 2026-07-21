from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.rfc import RFC
from app.models.backlog import BacklogItem
from app.models.project import Project
from app.services.engineering_graph import graph_sync

router = APIRouter()

STATUSES = ("draft", "review", "accepted", "rejected")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class RFCCreate(BaseModel):
    project_id: str
    feature_id: str | None = None
    title: str
    context: str
    proposal: str
    consequences: str | None = None
    status: str = "draft"


class RFCUpdate(BaseModel):
    feature_id: str | None = None
    title: str | None = None
    context: str | None = None
    proposal: str | None = None
    consequences: str | None = None
    status: str | None = None


@router.get("/rfcs")
def list_rfcs(project_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(RFC)
    if project_id:
        q = q.filter(RFC.project_id == project_id)
    return q.order_by(RFC.created_at.desc()).all()


@router.post("/rfcs", status_code=201)
def create_rfc(payload: RFCCreate, background_tasks: BackgroundTasks,
               db: Session = Depends(get_db)):
    if payload.status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"status inválido: {payload.status}")
    if not db.query(Project).filter(Project.id == payload.project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")
    if payload.feature_id:
        feature = db.query(BacklogItem).filter(
            BacklogItem.id == payload.feature_id,
            BacklogItem.project_id == payload.project_id,
            BacklogItem.type == "feature",
        ).first()
        if not feature:
            raise HTTPException(status_code=400, detail="Feature inválida para o projeto")

    rfc = RFC(**payload.model_dump())
    db.add(rfc)
    db.commit()
    db.refresh(rfc)
    background_tasks.add_task(
        graph_sync.sync_safely,
        "sync_related",
        "RFC",
        str(rfc.id),
        str(rfc.project_id),
        "LINKED_TO_RFC",
        str(rfc.feature_id) if rfc.feature_id else None,
    )
    return rfc


@router.patch("/rfcs/{rfc_id}")
def update_rfc(rfc_id: str, payload: RFCUpdate, db: Session = Depends(get_db)):
    rfc = db.query(RFC).filter(RFC.id == rfc_id).first()
    if not rfc:
        raise HTTPException(status_code=404, detail="RFC not found")
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in STATUSES:
        raise HTTPException(status_code=400, detail=f"status inválido: {data['status']}")
    if data.get("feature_id"):
        feature = db.query(BacklogItem).filter(
            BacklogItem.id == data["feature_id"],
            BacklogItem.project_id == rfc.project_id,
            BacklogItem.type == "feature",
        ).first()
        if not feature:
            raise HTTPException(status_code=400, detail="Feature inválida para o projeto")
    for field, value in data.items():
        setattr(rfc, field, value)
    db.commit()
    db.refresh(rfc)
    return rfc


@router.delete("/rfcs/{rfc_id}", status_code=204)
def delete_rfc(rfc_id: str, db: Session = Depends(get_db)):
    rfc = db.query(RFC).filter(RFC.id == rfc_id).first()
    if not rfc:
        raise HTTPException(status_code=404, detail="RFC not found")
    db.delete(rfc)
    db.commit()
