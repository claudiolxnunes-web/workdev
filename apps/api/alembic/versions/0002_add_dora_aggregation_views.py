"""add dora aggregation views

Revision ID: 0002
Revises: 40b39dbac1f6
Create Date: 2026-09-07

Views de agregação para as 4 métricas DORA:
1. deployment_frequency_weekly — deploys por semana
2. change_failure_rate_30d — taxa de falha dos últimos 30 dias
3. mttr_incidents — tempo de recuperação por incidente
4. lead_time_completed — tempo de criação até conclusão de tasks

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "40b39dbac1f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Criar views de agregação DORA."""

    # View 1: Frequência de deploy semanal
    op.execute("""
    CREATE OR REPLACE VIEW dora_deployment_frequency_weekly AS
    SELECT
        date_trunc('week', deployed_at) AS week_start,
        COUNT(*) FILTER (WHERE outcome = 'success') AS successful_count,
        COUNT(*) FILTER (WHERE outcome = 'degraded') AS degraded_count,
        COUNT(*) FILTER (WHERE outcome IN ('rolled_back', 'hotfixed')) AS failed_count,
        COUNT(*) AS total_count
    FROM deployment_outcomes
    GROUP BY date_trunc('week', deployed_at)
    ORDER BY week_start DESC;
    """)

    # View 2: Taxa de falha (últimos 30 dias)
    op.execute("""
    CREATE OR REPLACE VIEW dora_change_failure_rate_30d AS
    SELECT
        COUNT(*) FILTER (WHERE outcome IN ('rolled_back', 'hotfixed'))::numeric AS failed_count,
        COUNT(*)::numeric AS total_count,
        CASE
            WHEN COUNT(*) = 0 THEN 0
            ELSE (COUNT(*) FILTER (WHERE outcome IN ('rolled_back', 'hotfixed'))::numeric / COUNT(*)::numeric) * 100
        END AS failure_rate_percent
    FROM deployment_outcomes
    WHERE deployed_at >= (NOW() - INTERVAL '30 days');
    """)

    # View 3: MTTR — incidentes com tempo de recuperação
    op.execute("""
    CREATE OR REPLACE VIEW dora_mttr_incidents AS
    WITH incident_events AS (
        SELECT
            (payload->>'project_id') AS project_id,
            (payload->>'detected_at')::timestamptz AS detected_at,
            (payload->>'resolved_at')::timestamptz AS resolved_at,
            EXTRACT(EPOCH FROM (
                (payload->>'resolved_at')::timestamptz -
                (payload->>'detected_at')::timestamptz
            )) / 60 AS recovery_minutes
        FROM agent_run_events
        WHERE event_type = 'incident_resolved'
          AND payload ? 'detected_at'
          AND payload ? 'resolved_at'
    )
    SELECT
        detected_at,
        resolved_at,
        recovery_minutes,
        project_id
    FROM incident_events
    WHERE recovery_minutes > 0;
    """)

    # View 4: Lead time de tasks concluídas
    op.execute("""
    CREATE OR REPLACE VIEW dora_lead_time_completed AS
    SELECT
        id,
        project_id,
        EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600 AS lead_time_hours,
        created_at,
        updated_at
    FROM backlog
    WHERE status = 'done'
      AND updated_at > created_at;
    """)

    # View 5: Agregação mensal para dashboard histórico
    op.execute("""
    CREATE OR REPLACE VIEW dora_monthly_summary AS
    SELECT
        date_trunc('month', deployed_at) AS month_start,
        COUNT(*) AS total_deploys,
        COUNT(*) FILTER (WHERE outcome = 'success') AS successful_deploys,
        COUNT(*) FILTER (WHERE outcome IN ('rolled_back', 'hotfixed')) AS failed_deploys,
        (COUNT(*) FILTER (WHERE outcome IN ('rolled_back', 'hotfixed'))::numeric /
            NULLIF(COUNT(*), 0)::numeric) * 100 AS failure_rate
    FROM deployment_outcomes
    GROUP BY date_trunc('month', deployed_at)
    ORDER BY month_start DESC;
    """)


def downgrade() -> None:
    """Remover views de agregação DORA."""
    op.execute("DROP VIEW IF EXISTS dora_monthly_summary")
    op.execute("DROP VIEW IF EXISTS dora_lead_time_completed")
    op.execute("DROP VIEW IF EXISTS dora_mttr_incidents")
    op.execute("DROP VIEW IF EXISTS dora_change_failure_rate_30d")
    op.execute("DROP VIEW IF EXISTS dora_deployment_frequency_weekly")
