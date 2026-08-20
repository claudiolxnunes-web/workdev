"""AI Hub cost safety foundation.

Revision ID: e4a19c7d3b21
Revises: b7c1e4a9d520
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e4a19c7d3b21"
down_revision = "b7c1e4a9d520"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_model_catalog",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_model_id", sa.String(160), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("allowed_reasoning_efforts", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("context_window", sa.Integer()),
        sa.Column("input_cost_per_million", sa.Numeric(14, 6)),
        sa.Column("output_cost_per_million", sa.Numeric(14, 6)),
        sa.Column("supports_tools", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("supports_structured_output", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("supports_multimodal", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("is_free", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("allowed_fallbacks", postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("pricing_updated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("provider", "provider_model_id",
                            name="uq_ai_model_provider_id"),
    )
    op.create_table(
        "ai_budgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("scope_type", sa.String(24), nullable=False),
        sa.Column("scope_key", sa.String(160), nullable=False, server_default=""),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("limit_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("scope_type", "scope_key", "period",
                            name="uq_ai_budget_scope_period"),
    )
    op.execute(sa.text("""
        INSERT INTO ai_model_catalog
          (id, display_name, provider, provider_model_id, category,
           capabilities, allowed_reasoning_efforts, context_window,
           input_cost_per_million, output_cost_per_million, supports_tools,
           supports_structured_output, supports_multimodal, active, is_free,
           requires_confirmation, allowed_fallbacks, pricing_updated_at)
        VALUES
          ('openai-luna', 'GPT-5.6 Luna', 'openai', 'gpt-5.6-luna', 'economic',
           '["conversation","summary"]', '["low","medium"]', NULL,
           NULL, NULL, true, true, false, true, false, false, '[]', NULL),
          ('openai-terra', 'GPT-5.6 Terra', 'openai', 'gpt-5.6-terra', 'premium',
           '["reasoning","review"]', '["medium","high"]', NULL,
           NULL, NULL, true, true, false, true, false, true, '[]', NULL),
          ('openai-sol', 'GPT-5.6 Sol', 'openai', 'gpt-5.6-sol', 'premium',
           '["deep_reasoning","audit"]', '["high","max"]', NULL,
           NULL, NULL, true, true, false, true, false, true, '[]', NULL),
          ('openrouter-qwen3-coder', 'Qwen3 Coder', 'openrouter',
           'qwen/qwen3-coder', 'economic', '["code","prompt_generation"]',
           '[]', 262144, 0.30, 1.00, true, true, false, true, false, false,
           '[]', '2026-08-19T00:00:00Z'),
          ('openrouter-nemotron-ultra-free', 'Nemotron Ultra 550B Free',
           'openrouter', 'nvidia/nemotron-3-ultra-550b-a55b:free', 'free',
           '["planning","architecture"]', '[]', 1000000, 0, 0, true, true,
           false, true, true, false, '[]', '2026-08-19T00:00:00Z'),
          ('openrouter-kimi-k2-7-code', 'Kimi K2.7 Code', 'openrouter',
           'moonshotai/kimi-k2.7-code', 'economic',
           '["code","repository_analysis"]', '[]', 262144, 0.71, 3.50,
           true, true, false, true, false, false, '[]',
           '2026-08-19T00:00:00Z'),
          ('openrouter-kimi-k3', 'Kimi K3', 'openrouter', 'moonshotai/kimi-k3',
           'premium', '["multimodal","agentic"]', '[]', 1048576, 3.00,
           15.00, true, true, true, true, false, true, '[]',
           '2026-08-19T00:00:00Z')
    """))
    op.create_table(
        "ai_call_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False,
                  unique=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("chat_sessions.id", ondelete="SET NULL")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("user_id", sa.String(160), nullable=False),
        sa.Column("task_type", sa.String(40), nullable=False),
        sa.Column("requested_mode", sa.String(24)),
        sa.Column("requested_model", sa.String(160)),
        sa.Column("selected_model", sa.String(160), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("reasoning_effort", sa.String(16)),
        sa.Column("selection_reason", sa.Text(), nullable=False),
        sa.Column("fallback_occurred", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("fallback_reason", sa.Text()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("estimated_cost_usd", sa.Numeric(14, 8)),
        sa.Column("actual_cost_usd", sa.Numeric(14, 8)),
        sa.Column("is_free", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_type", sa.String(120)),
        sa.Column("premium_confirmed", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("confirmed_by", sa.String(160)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_ai_call_logs_created_at", "ai_call_logs", ["created_at"])
    op.create_index("ix_ai_call_logs_provider_model", "ai_call_logs",
                    ["provider", "selected_model"])
    op.create_index("ix_ai_call_logs_project_created", "ai_call_logs",
                    ["project_id", "created_at"])
    op.create_index("ix_ai_call_logs_user_created", "ai_call_logs",
                    ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("ai_call_logs")
    op.drop_table("ai_budgets")
    op.drop_table("ai_model_catalog")
