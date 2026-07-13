from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.project import Project

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/projects")
def get_projects(db: Session = Depends(get_db)):
    return db.query(Project).all()
from fastapi import HTTPException

@router.get("/projects/{slug}")
def get_project(slug: str, db: Session = Depends(get_db)):
    project = (
        db.query(Project)
        .filter(Project.slug == slug)
        .first()
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    return project
