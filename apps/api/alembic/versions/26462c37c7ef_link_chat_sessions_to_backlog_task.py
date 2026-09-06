"""link chat sessions to backlog task

Revision ID: 26462c37c7ef
Revises: 0001
Create Date: 2026-09-06 17:40:40.371507

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '26462c37c7ef'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE chat_sessions
        ADD COLUMN IF NOT EXISTS task_id uuid
        REFERENCES backlog(id) ON DELETE SET NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_sessions_task_id
        ON chat_sessions (task_id)
        WHERE task_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_chat_sessions_task_id")
    op.execute("""
        ALTER TABLE chat_sessions
        DROP COLUMN IF EXISTS task_id
    """)
