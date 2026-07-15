from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.chat import ChatSession, ChatMessage as ChatMessageDB

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/chat/sessions")
def listar_sessoes(db: Session = Depends(get_db)):
    rs = (db.query(ChatSession)
            .order_by(ChatSession.updated_at.desc())
            .limit(50).all())
    return [{"id": str(r.id), "title": r.title,
             "created_at": str(r.created_at),
             "updated_at": str(r.updated_at)} for r in rs]


@router.get("/chat/sessions/{session_id}")
def carregar_sessao(session_id: str, db: Session = Depends(get_db)):
    s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    msgs = (db.query(ChatMessageDB)
              .filter(ChatMessageDB.session_id == s.id)
              .order_by(ChatMessageDB.created_at.asc()).all())
    return {"id": str(s.id), "title": s.title,
            "messages": [{"role": m.role, "content": m.content} for m in msgs]}


@router.delete("/chat/sessions/{session_id}")
def apagar_sessao(session_id: str, db: Session = Depends(get_db)):
    s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    db.delete(s)
    db.commit()
    return {"ok": True}
