"""Backlog ganha o estado archived: colunas archived_at e archived_reason.

Revision ID: 20261012t120000
Revises: 20261001t220000
Create Date: 2026-10-12 12:00:00.000000

Encerramento não destrutivo de tasks (ADR 009). As duas colunas são nulas em
todo registro que não está arquivado; nenhuma linha existente muda de status.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20261012t120000"
down_revision: Union[str, Sequence[str], None] = "20261001t220000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("backlog", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.add_column("backlog", sa.Column("archived_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("backlog", "archived_reason")
    op.drop_column("backlog", "archived_at")
