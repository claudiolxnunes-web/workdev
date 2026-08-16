from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.chat import ChatSession, ChatMessage as ChatMessageDB
from app.models.project import Project
from app.schemas.chat import SessionUpdate

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def sessao_out(sessao: ChatSession, projeto: Project | None = None) -> dict:
    """Forma única da sessão na API — evita divergência entre listar e abrir."""
    return {
        "id": str(sessao.id),
        "title": sessao.title,
        "project_id": str(sessao.project_id) if sessao.project_id else None,
        "project_slug": projeto.slug if projeto else None,
        "project_name": projeto.name if projeto else None,
        "created_at": str(sessao.created_at),
        "updated_at": str(sessao.updated_at),
    }


def _projetos_das_sessoes(db: Session, sessoes: list[ChatSession]) -> dict:
    """Resolve os projetos em uma consulta só, não uma por sessão."""
    ids = {s.project_id for s in sessoes if s.project_id}
    if not ids:
        return {}
    return {
        projeto.id: projeto
        for projeto in db.query(Project).filter(Project.id.in_(ids)).all()
    }


def _get_sessao(db: Session, session_id: str) -> ChatSession:
    sessao = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not sessao:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    return sessao


@router.get("/chat/sessions")
def listar_sessoes(
    project_id: UUID | None = Query(
        None, description="filtra as conversas de um projeto"
    ),
    db: Session = Depends(get_db),
):
    consulta = db.query(ChatSession)
    if project_id is not None:
        consulta = consulta.filter(ChatSession.project_id == project_id)
    sessoes = consulta.order_by(ChatSession.updated_at.desc()).limit(50).all()
    projetos = _projetos_das_sessoes(db, sessoes)
    return [
        sessao_out(sessao, projetos.get(sessao.project_id)) for sessao in sessoes
    ]


@router.get("/chat/sessions/{session_id}")
def carregar_sessao(session_id: str, db: Session = Depends(get_db)):
    sessao = _get_sessao(db, session_id)
    mensagens = (
        db.query(ChatMessageDB)
        .filter(ChatMessageDB.session_id == sessao.id)
        .order_by(ChatMessageDB.created_at.asc())
        .all()
    )
    projeto = (
        db.query(Project).filter(Project.id == sessao.project_id).first()
        if sessao.project_id
        else None
    )
    return {
        **sessao_out(sessao, projeto),
        "messages": [
            {"role": m.role, "content": m.content} for m in mensagens
        ],
    }


@router.patch("/chat/sessions/{session_id}")
def atualizar_contexto(
    session_id: str,
    payload: SessionUpdate,
    db: Session = Depends(get_db),
):
    """Troca o projeto ativo da conversa.

    Omitir `project_id` não faz nada; mandar `null` devolve a conversa ao
    escopo global. A distinção é intencional e vem de `exclude_unset`.
    """
    sessao = _get_sessao(db, session_id)
    dados = payload.model_dump(exclude_unset=True)
    if "project_id" not in dados:
        raise HTTPException(status_code=422, detail="Nada a atualizar")

    projeto = None
    if dados["project_id"] is not None:
        projeto = (
            db.query(Project).filter(Project.id == dados["project_id"]).first()
        )
        if not projeto:
            raise HTTPException(status_code=422, detail="Projeto não encontrado")
        sessao.project_id = projeto.id
    else:
        sessao.project_id = None

    db.commit()
    db.refresh(sessao)
    return sessao_out(sessao, projeto)


@router.delete("/chat/sessions/{session_id}")
def apagar_sessao(session_id: str, db: Session = Depends(get_db)):
    sessao = _get_sessao(db, session_id)
    db.delete(sessao)
    db.commit()
    return {"ok": True}
