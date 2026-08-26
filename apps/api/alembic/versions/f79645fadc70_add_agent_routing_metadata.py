"""add agent routing metadata

Revision ID: f79645fadc70
Revises: e4a19c7d3b21
Create Date: 2026-08-26 19:05:47.788698

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f79645fadc70"
down_revision: Union[str, Sequence[str], None] = "e4a19c7d3b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runs",
        sa.Column("model", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("reasoning_effort", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("complexity", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column("complexity_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "routing_mode",
            sa.String(length=16),
            nullable=False,
            server_default="manual",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column("routing_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_runs", "routing_reason")
    op.drop_column("agent_runs", "routing_mode")
    op.drop_column("agent_runs", "complexity_score")
    op.drop_column("agent_runs", "complexity")
    op.drop_column("agent_runs", "reasoning_effort")
    op.drop_column("agent_runs", "model")
