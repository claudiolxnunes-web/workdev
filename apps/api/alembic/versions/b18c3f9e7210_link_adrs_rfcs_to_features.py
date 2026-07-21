"""link ADRs and RFCs to backlog features

Revision ID: b18c3f9e7210
Revises: 944f6834a6fd
Create Date: 2026-07-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b18c3f9e7210"
down_revision: Union[str, Sequence[str], None] = "944f6834a6fd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("adrs", sa.Column("feature_id", postgresql.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_adrs_feature_id_backlog", "adrs", "backlog",
        ["feature_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_adrs_feature_id", "adrs", ["feature_id"])

    op.add_column("rfcs", sa.Column("feature_id", postgresql.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_rfcs_feature_id_backlog", "rfcs", "backlog",
        ["feature_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_rfcs_feature_id", "rfcs", ["feature_id"])


def downgrade() -> None:
    op.drop_index("ix_rfcs_feature_id", table_name="rfcs")
    op.drop_constraint("fk_rfcs_feature_id_backlog", "rfcs", type_="foreignkey")
    op.drop_column("rfcs", "feature_id")

    op.drop_index("ix_adrs_feature_id", table_name="adrs")
    op.drop_constraint("fk_adrs_feature_id_backlog", "adrs", type_="foreignkey")
    op.drop_column("adrs", "feature_id")
