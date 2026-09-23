"""add local_model_key to agent_runs

Chave do modelo físico real servido pelo llama.cpp no momento do despacho
para o runtime local-code (q4/q2/bonsai, conforme local_model.current()).

Motivação: agent_runs.model grava o alias estável workdev-qwen27b de propósito
(a identidade local-code não muda quando o GGUF carregado muda), mas isso
esconde qual peso respondeu cada execução. Esta coluna registra a chave física
sem tocar no alias nem na coluna model.

Migração puramente aditiva: coluna nullable, sem default, nenhuma linha
existente é reescrita. Fica NULL para todo agent diferente de local-code.

Revision ID: 9f2b4d6a8c10
Revises: f3e1c9a42b77
Create Date: 2026-09-23 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f2b4d6a8c10"
down_revision: Union[str, Sequence[str], None] = "f3e1c9a42b77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runs",
        sa.Column(
            "local_model_key",
            sa.String(length=32),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_runs", "local_model_key")
