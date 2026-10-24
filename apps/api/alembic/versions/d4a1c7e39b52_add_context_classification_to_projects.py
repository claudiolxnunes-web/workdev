"""add context classification to projects

Classificação de sensibilidade do contexto enviado a runtimes de inferência.

Motivação (achado 7 de docs/plano-correcao-ollama.md): `build_context` monta
ADRs, knowledge, decisions e plano, e `augment_prompt` anexa os trechos. Hoje
esse prompt sai idêntico para `local-code` (loopback na própria VPS) e para
`gpu-hostinger`/`gpu-runpod` (internet, infraestrutura de terceiro). Não existe
nenhuma etapa entre os dois casos.

`internal` (default) — pode ir para runtime remoto, desde que haja consentimento
registrado e após o passe de redaction.
`restricted` — nunca sai da VPS, sem flag que contorne.

O default preserva o comportamento atual para todo projeto existente; endurecer
projeto a projeto é decisão do operador, não desta migração.

Revision ID: d4a1c7e39b52
Revises: c3f9a5b28d41
Create Date: 2026-09-09 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4a1c7e39b52"
down_revision: Union[str, Sequence[str], None] = "c3f9a5b28d41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "projects",
        sa.Column(
            "context_classification",
            sa.String(length=16),
            nullable=False,
            server_default="internal",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("projects", "context_classification")
