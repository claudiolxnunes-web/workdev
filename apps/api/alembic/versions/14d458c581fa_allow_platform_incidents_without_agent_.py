"""allow platform incidents without agent run

Revision ID: 14d458c581fa
Revises: 0002
Create Date: 2026-09-08 17:52:53.369981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '14d458c581fa'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow platform-level events without an AgentRun."""
    op.alter_column(
        "agent_run_events",
        "run_id",
        existing_type=sa.UUID(),
        nullable=True,
    )


def downgrade() -> None:
    """Require every event to belong to an AgentRun again."""
    op.alter_column(
        "agent_run_events",
        "run_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
