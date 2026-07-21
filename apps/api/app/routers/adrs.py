from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.adr import ADR
from app.models.backlog import BacklogItem
from app.models.project import Project
from app.services.engineering_graph import graph_sync

router = APIRouter()

STATUSES = ("proposed", "accepted", "deprecated", "superseded")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ADRCreate(BaseModel):
    project_id: str
    feature_id: str | None = None
    title: str
    context: str
    decision: str
    consequences: str | None = None
    status: str = "proposed"


class ADRUpdate(BaseModel):
    feature_id: str | None = None
    title: str | None = None
    context: str | None = None
    decision: str | None = None
    consequences: str | None = None
    status: str | None = None


@router.get("/adrs")
def list_adrs(project_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(ADR)
    if project_id:
        q = q.filter(ADR.project_id == project_id)
    return q.order_by(ADR.created_at.desc()).all()


@router.post("/adrs", status_code=201)
def create_adr(payload: ADRCreate, background_tasks: BackgroundTasks,
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

    adr = ADR(**payload.model_dump())
    db.add(adr)
    db.commit()
    db.refresh(adr)
    background_tasks.add_task(
        graph_sync.sync_safely,
        "sync_related",
        "ADR",
        str(adr.id),
        str(adr.project_id),
        "LINKED_TO_ADR",
        str(adr.feature_id) if adr.feature_id else None,
    )
    return adr


@router.patch("/adrs/{adr_id}")
def update_adr(adr_id: str, payload: ADRUpdate, db: Session = Depends(get_db)):
    adr = db.query(ADR).filter(ADR.id == adr_id).first()
    if not adr:
        raise HTTPException(status_code=404, detail="ADR not found")
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in STATUSES:
        raise HTTPException(status_code=400, detail=f"status inválido: {data['status']}")
    if data.get("feature_id"):
        feature = db.query(BacklogItem).filter(
            BacklogItem.id == data["feature_id"],
            BacklogItem.project_id == adr.project_id,
            BacklogItem.type == "feature",
        ).first()
        if not feature:
            raise HTTPException(status_code=400, detail="Feature inválida para o projeto")
    for field, value in data.items():
        setattr(adr, field, value)
    db.commit()
    db.refresh(adr)
    return adr


@router.delete("/adrs/{adr_id}", status_code=204)
def delete_adr(adr_id: str, db: Session = Depends(get_db)):
    adr = db.query(ADR).filter(ADR.id == adr_id).first()
    if not adr:
        raise HTTPException(status_code=404, detail="ADR not found")
    db.delete(adr)
    db.commit()
