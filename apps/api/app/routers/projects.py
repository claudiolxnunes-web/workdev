from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.project import Project

router = APIRouter()


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    stack: str | None = None
    vps: str | None = None
    github_url: str | None = None
    netlify_project: str | None = None
    vercel_project: str | None = None
    supabase_project: str | None = None
    dev_branch: str | None = None
    prod_branch: str | None = None

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/projects")
def get_projects(db: Session = Depends(get_db)):
    return db.query(Project).all()

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


@router.patch("/projects/{slug}")
def update_project(slug: str, payload: ProjectUpdate,
                    db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.slug == slug).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return project
