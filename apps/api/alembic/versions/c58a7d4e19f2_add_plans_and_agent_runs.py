"""add execution plans and agent runs

Revision ID: c58a7d4e19f2
Revises: af39d82c1107
Create Date: 2026-07-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c58a7d4e19f2"
down_revision: Union[str, Sequence[str], None] = "af39d82c1107"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_plans",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("backlog_id", postgresql.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="draft", nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text()),
        sa.Column("constraints", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("acceptance_criteria", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("validation_steps", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("implementation_notes", sa.Text()),
        sa.Column("created_by", sa.String(length=50), server_default="ai_hub", nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["backlog_id"], ["backlog.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("backlog_id", "version", name="uq_execution_plan_version"),
    )
    op.create_index("ix_execution_plans_backlog_id", "execution_plans", ["backlog_id"])
    op.create_index("ix_execution_plans_status", "execution_plans", ["status"])

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("plan_id", postgresql.UUID(), nullable=False),
        sa.Column("backlog_id", postgresql.UUID(), nullable=False),
        sa.Column("agent", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="queued", nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("result", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("branch", sa.String(length=255)),
        sa.Column("commit_sha", sa.String(length=64)),
        sa.Column("deployment_url", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["backlog_id"], ["backlog.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["execution_plans.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_plan_id", "agent_runs", ["plan_id"])
    op.create_index("ix_agent_runs_backlog_id", "agent_runs", ["backlog_id"])
    op.create_index("ix_agent_runs_agent_status", "agent_runs", ["agent", "status"])

    op.create_table(
        "agent_run_events",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", postgresql.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_run_events_run_id", "agent_run_events", ["run_id"])
    op.create_index("ix_agent_run_events_created_at", "agent_run_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_run_events_created_at", table_name="agent_run_events")
    op.drop_index("ix_agent_run_events_run_id", table_name="agent_run_events")
    op.drop_table("agent_run_events")
    op.drop_index("ix_agent_runs_agent_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_backlog_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_plan_id", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_execution_plans_status", table_name="execution_plans")
    op.drop_index("ix_execution_plans_backlog_id", table_name="execution_plans")
    op.drop_table("execution_plans")
