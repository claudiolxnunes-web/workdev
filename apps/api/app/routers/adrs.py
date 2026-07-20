from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.adr import ADR
from app.models.project import Project

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
    title: str
    context: str
    decision: str
    consequences: str | None = None
    status: str = "proposed"


class ADRUpdate(BaseModel):
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
def create_adr(payload: ADRCreate, db: Session = Depends(get_db)):
    if payload.status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"status inválido: {payload.status}")
    if not db.query(Project).filter(Project.id == payload.project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")

    adr = ADR(**payload.model_dump())
    db.add(adr)
    db.commit()
    db.refresh(adr)
    return adr


@router.patch("/adrs/{adr_id}")
def update_adr(adr_id: str, payload: ADRUpdate, db: Session = Depends(get_db)):
    adr = db.query(ADR).filter(ADR.id == adr_id).first()
    if not adr:
        raise HTTPException(status_code=404, detail="ADR not found")
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in STATUSES:
        raise HTTPException(status_code=400, detail=f"status inválido: {data['status']}")
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
