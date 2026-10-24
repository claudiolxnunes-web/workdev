"""add deployment outcomes

Revision ID: 0001
Revises: c7f21a9d4e05
Create Date: 2026-09-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = "c7f21a9d4e05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "deployment_outcomes",
        sa.Column("id", postgresql.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("proof_id", sa.String(64), nullable=False),
        sa.Column("project", sa.String(255), nullable=False),
        sa.Column("artifact_fingerprint", sa.String(64), nullable=False),
        sa.Column("outcome", sa.Enum(
            "success", "rolled_back", "hotfixed", "degraded",
            name="deployment_outcome"
        ), nullable=False),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deployed_by", sa.String(100), nullable=True),
        sa.Column("commit_sha", sa.String(64), nullable=True),
        sa.Column("deployment_url", sa.Text(), nullable=True),
        sa.Column("postcheck_result", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deployment_outcomes_proof_id", "deployment_outcomes", ["proof_id"])
    op.create_index("ix_deployment_outcomes_project", "deployment_outcomes", ["project"])
    op.create_index("ix_deployment_outcomes_deployed_at", "deployment_outcomes", ["deployed_at"])
    op.create_index("ix_deployment_outcomes_outcome", "deployment_outcomes", ["outcome"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_deployment_outcomes_outcome", table_name="deployment_outcomes")
    op.drop_index("ix_deployment_outcomes_deployed_at", table_name="deployment_outcomes")
    op.drop_index("ix_deployment_outcomes_project", table_name="deployment_outcomes")
    op.drop_index("ix_deployment_outcomes_proof_id", table_name="deployment_outcomes")
    op.drop_table("deployment_outcomes")

    op.execute("DROP TYPE IF EXISTS deployment_outcome")
