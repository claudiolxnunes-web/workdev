"""Ciclo de revisão persistido: decisão, métricas e auditoria por tentativa."""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class ReviewCycle(Base):
    """Uma linha por decisão de revisão de uma run; fechado quando o veredito
    chega (verdict + duration_ms). Nunca sobrescrito — escalonamentos criam
    novas linhas, então a série histórica responde "custo por risco" direto."""

    __tablename__ = 'review_cycles'

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()'))
    run_id = Column(UUID(as_uuid=True), ForeignKey('agent_runs.id', ondelete='CASCADE'), nullable=False)
    attempt = Column(Integer, nullable=False, server_default='1')
    decision = Column(String(24), nullable=False)
    tier = Column(String(16), nullable=False, server_default='none')
    task_risk = Column(String(16), nullable=False)
    agent_trust = Column(String(16), nullable=False)
    gate_result = Column(String(16), nullable=False)
    sensitive = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    justification = Column(Text, nullable=False)
    diff_files = Column(Integer, nullable=False, server_default='0')
    diff_lines = Column(Integer, nullable=False, server_default='0')
    context_bytes = Column(Integer, nullable=False, server_default='0')
    tokens_estimate = Column(Integer, nullable=False, server_default='0')
    reviewer_agent = Column(String(32))
    verdict = Column(String(16))
    escalated = Column(Boolean, nullable=False, server_default='false')
    duration_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text('now()'))
    closed_at = Column(DateTime(timezone=True))

    __table_args__ = (Index('ix_review_cycles_run_id', 'run_id'),)
