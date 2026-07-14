"""reference: backlog_subtasks (criada manualmente)

Revision ID: fd3d7d40a027
Revises: 9482064eb825
Create Date: 2026-07-14 11:31:43.823137

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fd3d7d40a027'
down_revision: Union[str, Sequence[str], None] = '9482064eb825'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
