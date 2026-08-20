from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, Numeric, String,
    Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class AIModelCatalog(Base):
    __tablename__ = "ai_model_catalog"

    id = Column(String(80), primary_key=True)
    display_name = Column(String(120), nullable=False)
    provider = Column(String(32), nullable=False)
    provider_model_id = Column(String(160), nullable=False)
    category = Column(String(24), nullable=False)
    capabilities = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    allowed_reasoning_efforts = Column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    context_window = Column(Integer)
    input_cost_per_million = Column(Numeric(14, 6))
    output_cost_per_million = Column(Numeric(14, 6))
    supports_tools = Column(Boolean, nullable=False, server_default=text("false"))
    supports_structured_output = Column(
        Boolean, nullable=False, server_default=text("false")
    )
    supports_multimodal = Column(Boolean, nullable=False, server_default=text("false"))
    active = Column(Boolean, nullable=False, server_default=text("true"))
    is_free = Column(Boolean, nullable=False, server_default=text("false"))
    requires_confirmation = Column(
        Boolean, nullable=False, server_default=text("false")
    )
    allowed_fallbacks = Column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    pricing_updated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("provider", "provider_model_id", name="uq_ai_model_provider_id"),
    )


class AIBudget(Base):
    __tablename__ = "ai_budgets"

    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    scope_type = Column(String(24), nullable=False)
    scope_key = Column(String(160), nullable=False, server_default="")
    period = Column(String(16), nullable=False)
    limit_usd = Column(Numeric(14, 6), nullable=False)
    active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("scope_type", "scope_key", "period",
                         name="uq_ai_budget_scope_period"),
    )


class AICallLog(Base):
    __tablename__ = "ai_call_logs"

    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    correlation_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    session_id = Column(UUID(as_uuid=True),
                        ForeignKey("chat_sessions.id", ondelete="SET NULL"))
    project_id = Column(UUID(as_uuid=True),
                        ForeignKey("projects.id", ondelete="SET NULL"))
    user_id = Column(String(160), nullable=False)
    task_type = Column(String(40), nullable=False)
    requested_mode = Column(String(24))
    requested_model = Column(String(160))
    selected_model = Column(String(160), nullable=False)
    provider = Column(String(32), nullable=False)
    reasoning_effort = Column(String(16))
    selection_reason = Column(Text, nullable=False)
    fallback_occurred = Column(Boolean, nullable=False, server_default=text("false"))
    fallback_reason = Column(Text)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    estimated_cost_usd = Column(Numeric(14, 8))
    actual_cost_usd = Column(Numeric(14, 8))
    is_free = Column(Boolean, nullable=False, server_default=text("false"))
    duration_ms = Column(Integer)
    success = Column(Boolean, nullable=False)
    error_type = Column(String(120))
    premium_confirmed = Column(Boolean, nullable=False, server_default=text("false"))
    confirmed_by = Column(String(160))
    confirmed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("ix_ai_call_logs_created_at", "created_at"),
        Index("ix_ai_call_logs_provider_model", "provider", "selected_model"),
        Index("ix_ai_call_logs_project_created", "project_id", "created_at"),
        Index("ix_ai_call_logs_user_created", "user_id", "created_at"),
    )
