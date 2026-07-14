"""reference: backlog_subtasks

Revision ID: 7c6e17952774
Revises: fd3d7d40a027
Create Date: 2026-07-14 11:53:23.888858

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c6e17952774'
down_revision: Union[str, Sequence[str], None] = 'fd3d7d40a027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
