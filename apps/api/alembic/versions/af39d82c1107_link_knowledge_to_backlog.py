"""link knowledge entries to backlog items

Revision ID: af39d82c1107
Revises: b18c3f9e7210
Create Date: 2026-07-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "af39d82c1107"
down_revision: Union[str, Sequence[str], None] = "b18c3f9e7210"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge",
        sa.Column("backlog_id", postgresql.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_backlog_id_backlog",
        "knowledge",
        "backlog",
        ["backlog_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_knowledge_backlog_id", "knowledge", ["backlog_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_backlog_id", table_name="knowledge")
    op.drop_constraint(
        "fk_knowledge_backlog_id_backlog", "knowledge", type_="foreignkey"
    )
    op.drop_column("knowledge", "backlog_id")
