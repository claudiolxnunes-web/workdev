from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.decision import Decision
from app.models.project import Project
from app.services.engineering_graph import graph_sync

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class DecisionCreate(BaseModel):
    project_id: str
    title: str
    description: str


@router.get("/decisions")
def list_decisions(project_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Decision)
    if project_id:
        q = q.filter(Decision.project_id == project_id)
    return q.order_by(Decision.created_at.desc()).all()


@router.post("/decisions", status_code=201)
def create_decision(payload: DecisionCreate, background_tasks: BackgroundTasks,
                    db: Session = Depends(get_db)):
    if not db.query(Project).filter(Project.id == payload.project_id).first():
        raise HTTPException(status_code=404, detail="Project not found")

    decision = Decision(**payload.model_dump())
    db.add(decision)
    db.commit()
    db.refresh(decision)
    background_tasks.add_task(
        graph_sync.sync_safely,
        "sync_related",
        "Decision",
        str(decision.id),
        str(decision.project_id),
        "HAS_DECISION",
    )
    return decision


@router.delete("/decisions/{decision_id}", status_code=204)
def delete_decision(decision_id: str, background_tasks: BackgroundTasks,
                     db: Session = Depends(get_db)):
    decision = db.query(Decision).filter(Decision.id == decision_id).first()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    # O node e as edges saem juntos com a Decision: o Postgres e a fonte da verdade.
    project_id = str(decision.project_id) if decision.project_id else None
    db.delete(decision)
    db.commit()
    background_tasks.add_task(
        graph_sync.delete_safely, "Decision", str(decision_id), project_id)
