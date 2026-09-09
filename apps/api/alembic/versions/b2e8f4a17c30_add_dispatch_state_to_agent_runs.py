"""add dispatch state to agent_runs

Estado de despacho persistido para runs executadas por runtime Ollama.

Motivação (ver docs/plano-correcao-ollama.md, achados 5 e 6): hoje o despacho
acontece inteiro dentro da requisição HTTP, sem estado no banco. Duas chamadas
concorrentes disparam duas inferências, e a rota segura a sessão do SQLAlchemy
por até 900s. Sem estado persistido não há como um worker retomar, nem como a UI
mostrar o que está acontecendo.

Migração puramente aditiva: todas as colunas são nullable ou têm server_default,
então nenhuma linha existente precisa ser reescrita e o código antigo continua
funcionando com o schema novo.

Revision ID: b2e8f4a17c30
Revises: a1c7e5b93f10
Create Date: 2026-09-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b2e8f4a17c30"
down_revision: Union[str, Sequence[str], None] = "a1c7e5b93f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # idle | queued | dispatching | dispatched | failed
    #
    # Separado de `status`: `status` é o ciclo de vida da run no contrato
    # PLAN → BUILD (ADR 004) e não pode ser sobrecarregado com o estado
    # operacional do despacho, sob pena de inventar transições que o
    # RUN_TRANSITIONS não conhece.
    op.add_column(
        "agent_runs",
        sa.Column(
            "dispatch_state",
            sa.String(length=16),
            nullable=False,
            server_default="idle",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "dispatch_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "last_dispatch_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Token de idempotência: o cliente reenvia o mesmo token numa retentativa e
    # recebe o job existente em vez de criar um segundo.
    op.add_column(
        "agent_runs",
        sa.Column(
            "dispatch_token",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_agent_runs_dispatch_state",
        "agent_runs",
        ["dispatch_state"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_agent_runs_dispatch_state", table_name="agent_runs")
    op.drop_column("agent_runs", "dispatch_token")
    op.drop_column("agent_runs", "last_dispatch_at")
    op.drop_column("agent_runs", "dispatch_attempts")
    op.drop_column("agent_runs", "dispatch_state")
