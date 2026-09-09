from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, text,
)

from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class ExecutionPlan(Base):
    __tablename__ = "execution_plans"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    backlog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("backlog.id", ondelete="CASCADE"),
        nullable=False,
    )
    version = Column(Integer, nullable=False)
    status = Column(String(24), nullable=False, server_default="draft")
    title = Column(String(255), nullable=False)
    objective = Column(Text, nullable=False)
    scope = Column(Text)
    constraints = Column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    acceptance_criteria = Column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    validation_steps = Column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    implementation_notes = Column(Text)
    created_by = Column(
        String(50),
        nullable=False,
        server_default="ai_hub",
    )
    approved_at = Column(DateTime(timezone=True))
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "backlog_id",
            "version",
            name="uq_execution_plan_version",
        ),
        Index("ix_execution_plans_backlog_id", "backlog_id"),
        Index("ix_execution_plans_status", "status"),
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    plan_id = Column(
        UUID(as_uuid=True),
        ForeignKey("execution_plans.id", ondelete="RESTRICT"),
        nullable=False,
    )
    backlog_id = Column(
        UUID(as_uuid=True),
        ForeignKey("backlog.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Executor da run. Identidade lógica do agente (codex, claude, local-code,
    # gpu-hostinger…), nunca o modelo carregado — modelo é `model`.
    agent = Column(String(32), nullable=False)

    # Revisor independente escolhido na aprovação do PLAN. Nunca pode ser igual
    # ao executor na revisão final (validado em app/services/handoff.py).
    reviewer_agent = Column(String(32))

    # Quantas rodadas de revisão já foram registradas para esta run. O histórico
    # detalhado vive em agent_run_reviews e é cumulativo (nunca sobrescrito).
    review_attempts = Column(
        Integer,
        nullable=False,
        server_default="0",
    )

    model = Column(String(120))
    reasoning_effort = Column(String(16))
    complexity = Column(String(16))
    complexity_score = Column(Integer)
    routing_mode = Column(
        String(16),
        nullable=False,
        server_default="manual",
    )
    routing_reason = Column(Text)

    status = Column(
        String(24),
        nullable=False,
        server_default="queued",
    )
    summary = Column(Text)
    result = Column(Text)
    error = Column(Text)
    branch = Column(String(255))
    commit_sha = Column(String(64))
    deployment_url = Column(Text)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        Index("ix_agent_runs_plan_id", "plan_id"),
        Index("ix_agent_runs_backlog_id", "backlog_id"),
        Index("ix_agent_runs_agent_status", "agent", "status"),
        Index("ix_agent_runs_reviewer_agent", "reviewer_agent"),
    )


class AgentRunReview(Base):
    """Histórico cumulativo de revisões independentes de uma execução.

    Cada tentativa vira uma linha nova: rejeição não apaga nem sobrescreve a
    anterior, então a trilha de auditoria (quem revisou, quando, com qual
    veredito e feedback) sobrevive a quantas correções forem necessárias.
    """

    __tablename__ = "agent_run_reviews"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt = Column(Integer, nullable=False)
    executor_agent = Column(String(32), nullable=False)
    reviewer_agent = Column(String(32), nullable=False)
    verdict = Column(String(16), nullable=False)
    feedback = Column(Text)
    gate_passed = Column(Boolean)
    payload = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "attempt",
            name="uq_agent_run_review_attempt",
        ),
        Index("ix_agent_run_reviews_run_id", "run_id"),
        Index("ix_agent_run_reviews_created_at", "created_at"),
    )


class AgentRunEvent(Base):
    __tablename__ = "agent_run_events"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=True,
    )
    event_type = Column(String(40), nullable=False)
    message = Column(Text)
    payload = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        Index("ix_agent_run_events_run_id", "run_id"),
        Index("ix_agent_run_events_created_at", "created_at"),
    )
