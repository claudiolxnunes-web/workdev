"""Telemetria por AgentRun: provider na run e tabela agent_run_telemetry.

Revision ID: 20261027t090000
Revises: 20261012t120000
Create Date: 2026-10-27 09:00:00.000000

Duas mudanças independentes:

1. `agent_runs.provider` — o par provider/model já era auditável pelo evento
   `build.queued`, mas não por coluna. Nulo nas runs históricas; a partir
   daqui a escolha fica consultável por run.

2. `agent_run_telemetry` — consumo de tokens e custo por chamada de provedor.
   Tabela separada, e não colunas em `agent_runs`: uma run pode ter mais de
   uma chamada de provedor, e misturar o agregado com o registro da run perde
   a granularidade.

Duas colunas carregam o peso do desenho:

- `source` distingue **oficial** (o número veio da API do provedor ou do
  runtime) de **estimado** (derivado do transcript e do preço de catálogo).
  Sem ela, um número estimado apareceria ao lado de um número faturado como
  se fossem a mesma coisa.
- `cost_class` separa o que é despesa marginal do que já está pago: CLI
  local, franquia gratuita, plano de assinatura e API cobrada por token.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20261027t090000"
down_revision: Union[str, Sequence[str], None] = "20261012t120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("provider", sa.String(length=60), nullable=True))

    op.create_table(
        "agent_run_telemetry",
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
        sa.Column(
            "backlog_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("backlog.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("agent", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("actual_cost", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            server_default="USD",
        ),
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
        ),
        sa.Column(
            "cost_class",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # `source` NOT NULL de propósito, e sem default: ninguém grava número
        # sem dizer de onde ele veio.
        sa.CheckConstraint(
            "source IN ('official', 'estimated')",
            name="ck_agent_run_telemetry_source",
        ),
        sa.CheckConstraint(
            "cost_class IN ('local', 'free_quota', 'included_plan', 'paid_api')",
            name="ck_agent_run_telemetry_cost_class",
        ),
    )

    op.create_index(
        "ix_agent_run_telemetry_run_id",
        "agent_run_telemetry",
        ["run_id"],
    )
    op.create_index(
        "ix_agent_run_telemetry_agent",
        "agent_run_telemetry",
        ["agent", "recorded_at"],
    )
    op.create_index(
        "ix_agent_run_telemetry_project",
        "agent_run_telemetry",
        ["project_id", "recorded_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_run_telemetry_project", table_name="agent_run_telemetry")
    op.drop_index("ix_agent_run_telemetry_agent", table_name="agent_run_telemetry")
    op.drop_index("ix_agent_run_telemetry_run_id", table_name="agent_run_telemetry")
    op.drop_table("agent_run_telemetry")
    op.drop_column("agent_runs", "provider")
