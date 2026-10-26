"""Coleta das referências canônicas de um projeto: ADR, knowledge e decisions.

Mesmo recorte do `build_context` (projeto + feature da task ou sem feature, as
20 mais recentes de cada), no formato que o `build_rag` entende. Existe para o
Workspace Local, que não tem `agent_run` e por isso não passa pelo
`build_context`: o supervisor recebe o bloco canônico no prompt de abertura e
lê o conteúdo inteiro pela tool `ler_referencias`.
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.adr import ADR
from app.models.decision import Decision
from app.models.knowledge import KnowledgeEntry

LIMITE = 20


def coletar(db: Session, project_id, task_id=None, limite: int = LIMITE) -> dict:
    adrs = db.query(ADR).filter(ADR.project_id == project_id)
    knowledge = db.query(KnowledgeEntry)
    if task_id is not None:
        adrs = adrs.filter(or_(ADR.feature_id == task_id, ADR.feature_id.is_(None)))
        knowledge = knowledge.filter(or_(KnowledgeEntry.backlog_id == task_id,
                                         KnowledgeEntry.project_id == project_id))
    else:
        knowledge = knowledge.filter(KnowledgeEntry.project_id == project_id)
    decisions = db.query(Decision).filter(Decision.project_id == project_id)

    return {
        "adrs": [
            {"id": str(r.id), "title": r.title, "context": r.context, "decision": r.decision,
             "consequences": r.consequences, "status": r.status}
            for r in adrs.order_by(ADR.created_at.desc()).limit(limite).all()
        ],
        "knowledge": [
            {"id": str(r.id), "title": r.title, "content": r.content, "category": r.category}
            for r in knowledge.order_by(KnowledgeEntry.created_at.desc()).limit(limite).all()
        ],
        "decisions": [
            {"id": str(r.id), "title": r.title, "description": r.description}
            for r in decisions.order_by(Decision.created_at.desc()).limit(limite).all()
        ],
    }
