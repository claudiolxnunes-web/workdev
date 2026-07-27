"""add execution plan title

Revision ID: 2c53d77a9f4b
Revises: c58a7d4e19f2
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2c53d77a9f4b"
down_revision: Union[str, Sequence[str], None] = "c58a7d4e19f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("execution_plans", sa.Column("title", sa.String(255)))
    op.execute(
        """
        UPDATE execution_plans AS plan
        SET title = backlog.title
        FROM backlog
        WHERE backlog.id = plan.backlog_id
        """
    )
    op.alter_column("execution_plans", "title", nullable=False)


def downgrade() -> None:
    op.drop_column("execution_plans", "title")
