from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.rfc import RFC
from app.models.project import Project

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
    title: str
    context: str
    proposal: str
    consequences: str | None = None
    status: str = "draft"


class RFCUpdate(BaseModel):
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
def create_rfc(payload: RFCCreate, db: Session = Depends(get_db)):
    if payload.status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"status inválido: {payload.status}")
    if not db.query(Project).filter(Project.id == payload.project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")

    rfc = RFC(**payload.model_dump())
    db.add(rfc)
    db.commit()
    db.refresh(rfc)
    return rfc


@router.patch("/rfcs/{rfc_id}")
def update_rfc(rfc_id: str, payload: RFCUpdate, db: Session = Depends(get_db)):
    rfc = db.query(RFC).filter(RFC.id == rfc_id).first()
    if not rfc:
        raise HTTPException(status_code=404, detail="RFC not found")
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in STATUSES:
        raise HTTPException(status_code=400, detail=f"status inválido: {data['status']}")
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
