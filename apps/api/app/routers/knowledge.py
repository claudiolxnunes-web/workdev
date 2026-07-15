from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.knowledge import KnowledgeEntry

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/knowledge")
def listar_conhecimento(categoria: str | None = None,
                        termo: str | None = None,
                        db: Session = Depends(get_db)):
    q = db.query(KnowledgeEntry)
    if categoria:
        q = q.filter(KnowledgeEntry.category == categoria)
    if termo:
        t = f"%{termo}%"
        q = q.filter(KnowledgeEntry.title.ilike(t)
                     | KnowledgeEntry.content.ilike(t)
                     | KnowledgeEntry.tags.ilike(t))
    rs = q.order_by(KnowledgeEntry.created_at.desc()).all()
    return [{"id": str(r.id), "title": r.title, "content": r.content,
             "category": r.category, "tags": r.tags,
             "created_at": str(r.created_at)} for r in rs]
