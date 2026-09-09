"""create agent_build_jobs

Fila de despacho consumida pelo worker de build isolado (ADR 005).

A garantia central desta tabela é o índice único PARCIAL sobre `run_id` restrito
aos estados ativos: o banco — não a aplicação — impede dois despachos
simultâneos para a mesma run. É a correção do achado 5 de
docs/plano-correcao-ollama.md, onde dois POSTs concorrentes disparavam duas
inferências e gravavam dois eventos.

O worker consome com `SELECT ... FOR UPDATE SKIP LOCKED`, o que permite mais de
um worker no futuro sem mudança de schema.

Nenhum conteúdo de prompt é armazenado aqui: só o SHA-256, para correlacionar
sem persistir contexto que pode conter dado sensível.

Revision ID: c3f9a5b28d41
Revises: b2e8f4a17c30
Create Date: 2026-09-09 12:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c3f9a5b28d41"
down_revision: Union[str, Sequence[str], None] = "b2e8f4a17c30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ACTIVE_STATES = ("queued", "running")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_build_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Identidade do runtime (local-code, gpu-hostinger, gpu-runpod).
        # Nunca a URL nem o token: esses vivem só em variável de ambiente.
        sa.Column("runtime_id", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        # queued | running | succeeded | failed | cancelled
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "attempt",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        # Só o hash do prompt. O prompt em si nunca é persistido.
        sa.Column("prompt_sha256", sa.String(length=64), nullable=True),
        sa.Column("branch", sa.String(length=120), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_agent_build_jobs_run_id",
        "agent_build_jobs",
        ["run_id"],
    )
    op.create_index(
        "ix_agent_build_jobs_state",
        "agent_build_jobs",
        ["state"],
    )

    # A trava de concorrência. Sem isto, o achado 5 volta na primeira corrida.
    op.create_index(
        "uq_agent_build_jobs_active_run",
        "agent_build_jobs",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('queued', 'running')"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_agent_build_jobs_active_run",
        table_name="agent_build_jobs",
    )
    op.drop_index("ix_agent_build_jobs_state", table_name="agent_build_jobs")
    op.drop_index("ix_agent_build_jobs_run_id", table_name="agent_build_jobs")
    op.drop_table("agent_build_jobs")
