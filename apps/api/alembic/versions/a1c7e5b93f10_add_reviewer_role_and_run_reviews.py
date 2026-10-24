"""add reviewer role and cumulative run reviews

Revision ID: a1c7e5b93f10
Revises: 14d458c581fa
Create Date: 2026-09-09 03:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a1c7e5b93f10"
down_revision: Union[str, Sequence[str], None] = "14d458c581fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Identidades de runtime local/GPU (local-code, gpu-hostinger, gpu-runpod)
    # não cabem confortavelmente em 20 chars; o campo passa a 32.
    op.alter_column(
        "agent_runs",
        "agent",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.add_column(
        "agent_runs",
        sa.Column("reviewer_agent", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "review_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_agent_runs_reviewer_agent",
        "agent_runs",
        ["reviewer_agent"],
    )

    op.create_table(
        "agent_run_reviews",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("executor_agent", sa.String(length=32), nullable=False),
        sa.Column("reviewer_agent", sa.String(length=32), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("gate_passed", sa.Boolean(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "run_id",
            "attempt",
            name="uq_agent_run_review_attempt",
        ),
    )
    op.create_index(
        "ix_agent_run_reviews_run_id",
        "agent_run_reviews",
        ["run_id"],
    )
    op.create_index(
        "ix_agent_run_reviews_created_at",
        "agent_run_reviews",
        ["created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_agent_run_reviews_created_at",
        table_name="agent_run_reviews",
    )
    op.drop_index(
        "ix_agent_run_reviews_run_id",
        table_name="agent_run_reviews",
    )
    op.drop_table("agent_run_reviews")
    op.drop_index("ix_agent_runs_reviewer_agent", table_name="agent_runs")
    op.drop_column("agent_runs", "review_attempts")
    op.drop_column("agent_runs", "reviewer_agent")
    op.alter_column(
        "agent_runs",
        "agent",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
