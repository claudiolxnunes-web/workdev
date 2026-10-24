"""Persistência de feedback de revisão como KnowledgeEntry.

Objetivo:
- tornar acertos e erros anteriores recuperáveis pelo RAG lexical;
- não duplicar conhecimento se o mesmo review for processado novamente;
- não criar schema/tabela nova.

Knowledge continua sendo a fonte canônica usada pelo build_rag.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.backlog import BacklogItem
from app.models.handoff import AgentRun, AgentRunReview
from app.models.knowledge import KnowledgeEntry


def persist_review_knowledge(
    db: Session,
    run: AgentRun,
    review: AgentRunReview,
) -> KnowledgeEntry | None:
    """Cria uma lição RAG para uma revisão, de forma idempotente."""

    payload = review.payload or {}

    if payload.get("rag_eligible") is not True:
        return None

    review_tag = f"agent-feedback,review:{review.id}"

    existing = (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.tags == review_tag)
        .first()
    )

    if existing is not None:
        return existing

    backlog = (
        db.query(BacklogItem)
        .filter(BacklogItem.id == run.backlog_id)
        .first()
    )

    project_id = backlog.project_id if backlog is not None else None

    category = payload.get("feedback_category") or "other"
    confidence = payload.get("feedback_confidence") or "unknown"
    reason = payload.get("feedback_reason") or "Não informado"

    title = (
        f"[feedback][{category}] "
        f"{run.agent} — revisão {review.attempt}"
    )[:255]

    content = "\n".join(
        [
            "Lição automática derivada de revisão independente do WorkDev.",
            "",
            f"Executor: {run.agent}",
            f"Modelo: {getattr(run, 'model', None) or 'não informado'}",
            f"Revisor: {review.reviewer_agent}",
            f"Veredito: {review.verdict}",
            f"Gate aprovado: {review.gate_passed}",
            f"Categoria: {category}",
            f"Confiança: {confidence}",
            f"Motivo da classificação: {reason}",
            "",
            "Feedback do revisor:",
            review.feedback or "Nenhum feedback textual.",
            "",
            "Resultado registrado pelo executor:",
            run.result or "Nenhum resultado textual registrado.",
            "",
            f"Review ID: {review.id}",
            f"Run ID: {run.id}",
        ]
    )

    entry = KnowledgeEntry(
        project_id=project_id,
        backlog_id=run.backlog_id,
        title=title,
        content=content,
        category="licao",
        tags=review_tag,
    )

    db.add(entry)
    db.flush()

    return entry
