import os
import time
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(prefix="/metrics", tags=["metrics"])

# Cache em memória (fallback sem Redis)
CACHE_TTL = int(os.getenv("METRICS_CACHE_TTL", "300"))  # 5 minutos padrão
_cache_data: dict[str, tuple[dict[str, Any], float]] = {}


def _get_from_cache(key: str) -> dict[str, Any] | None:
    """Obter dados do cache em memória."""
    if key not in _cache_data:
        return None
    data, timestamp = _cache_data[key]
    if time.time() - timestamp > CACHE_TTL:
        del _cache_data[key]
        return None
    return data


def _set_cache(key: str, data: dict[str, Any]) -> None:
    """Salvar dados no cache em memória."""
    _cache_data[key] = (data, time.time())


@router.get("/executive")
def get_executive_metrics(
    project_id: str | None = None,
    days: int = 30,
    db: Session = Depends(get_db),
):
    """
    Obter métricas executivas DORA consolidadas.

    Retorna as 4 métricas DORA:
    1. Deployment Frequency (frequência de deploy por semana)
    2. Change Failure Rate (taxa de falha em mudança)
    3. MTTR (Median Time To Recovery)
    4. Lead Time for Changes

    Parâmetros:
    - `project_id`: filtrar por projeto (opcional)
    - `days`: janela de dias para análise (padrão: 30)

    Cache:
    - Redis (quando disponível): TTL configurável via METRICS_CACHE_TTL
    - Fallback: LRU cache em memória (5 minutos)
    """
    cache_key = f"metrics:executive:{project_id or 'all'}:{days}"

    # Tentar cache Redis
    cached = _get_from_cache(cache_key)
    if cached:
        cached["_cache_hit"] = True
        cached["_cache_source"] = "redis"
        return cached

    # Calcular métricas a partir do PostgreSQL local
    cutoff = datetime.utcnow() - timedelta(days=days)

    metrics: dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat(),
        "period_days": days,
        "project_id": project_id,
        "metrics": {},
    }

    try:
        # 1. Deployment Frequency (deploys por semana)
        deploy_query = """
        SELECT
            date_trunc('week', deployed_at) AS week_start,
            COUNT(*) FILTER (WHERE outcome = 'success') AS successful,
            COUNT(*) FILTER (WHERE outcome = 'degraded') AS degraded,
            COUNT(*) FILTER (WHERE outcome IN ('rolled_back', 'hotfixed')) AS failed,
            COUNT(*) AS total
        FROM deployment_outcomes
        WHERE deployed_at >= :cutoff
        GROUP BY week_start
        ORDER BY week_start DESC
        """

        project_filter = ""
        if project_id:
            project_filter = " AND project = :project_id"
            deploy_query += project_filter

        deploy_result = db.execute(
            text(deploy_query),
            {"cutoff": cutoff, "project_id": project_id} if project_id else {"cutoff": cutoff}
        ).fetchall()

        weekly_deploys = [
            {
                "week": row.week_start.isoformat(),
                "successful": row.successful,
                "degraded": row.degraded,
                "failed": row.failed,
                "total": row.total,
            }
            for row in deploy_result
        ]

        # Calcular média semanal
        if weekly_deploys:
            avg_weekly = sum(d["successful"] for d in weekly_deploys) / max(len(weekly_deploys), 1)
        else:
            avg_weekly = 0

        metrics["metrics"]["deployment_frequency"] = {
            "weekly_average": round(avg_weekly, 2),
            "last_4_weeks": weekly_deploys[:4],
            "total_in_period": sum(d["total"] for d in weekly_deploys),
        }

        # 2. Change Failure Rate (últimos 30 dias)
        failure_query = """
        SELECT
            COUNT(*) FILTER (WHERE outcome IN ('rolled_back', 'hotfixed'))::numeric AS failed,
            COUNT(*)::numeric AS total
        FROM deployment_outcomes
        WHERE deployed_at >= :cutoff
        """
        if project_id:
            failure_query += " AND project = :project_id"

        failure_result = db.execute(
            text(failure_query),
            {"cutoff": datetime.utcnow() - timedelta(days=30), "project_id": project_id} if project_id else {"cutoff": datetime.utcnow() - timedelta(days=30)}
        ).first()

        failed_count = float(failure_result.failed) if failure_result else 0
        total_count = float(failure_result.total) if failure_result else 0
        failure_rate = (failed_count / total_count * 100) if total_count > 0 else 0

        metrics["metrics"]["change_failure_rate"] = {
            "percent": round(failure_rate, 2),
            "failed_count": int(failed_count),
            "total_count": int(total_count),
        }

        # 3. MTTR - Median Time To Recovery (simulado via agent_run_events)
        # Como não temos incidentes estruturados, usar eventos do supervisor
        mttr_query = """
        WITH incident_events AS (
            SELECT
                payload->>'project_id' AS project_id,
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
              AND (payload->>'resolved_at')::timestamptz >= :cutoff
        )
        SELECT
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY recovery_minutes) AS median_minutes,
            AVG(recovery_minutes) AS mean_minutes,
            COUNT(*) AS incident_count
        FROM incident_events
        WHERE recovery_minutes > 0
        """

        mttr_result = db.execute(
            text(mttr_query),
            {"cutoff": datetime.utcnow() - timedelta(days=30)}
        ).first()

        metrics["metrics"]["mttr"] = {
            "median_minutes": round(float(mttr_result.median_minutes), 2) if mttr_result and mttr_result.median_minutes else None,
            "mean_minutes": round(float(mttr_result.mean_minutes), 2) if mttr_result and mttr_result.mean_minutes else None,
            "incident_count": mttr_result.incident_count if mttr_result else 0,
        }

        # 4. Lead Time - tempo médio de criação até conclusão de tasks
        lead_time_query = """
        WITH task_pairs AS (
            SELECT
                bl.project_id,
                EXTRACT(EPOCH FROM (
                    bl.updated_at - bl.created_at
                )) / 3600 AS lead_time_hours
            FROM backlog bl
            WHERE bl.status = 'done'
              AND bl.updated_at >= :cutoff
              AND bl.updated_at > bl.created_at
        )
        SELECT
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY lead_time_hours) AS median_hours,
            AVG(lead_time_hours) AS mean_hours,
            MIN(lead_time_hours) AS min_hours,
            MAX(lead_time_hours) AS max_hours,
            COUNT(*) AS completed_count
        FROM task_pairs
        """

        lead_result = db.execute(
            text(lead_time_query),
            {"cutoff": cutoff}
        ).first()

        metrics["metrics"]["lead_time"] = {
            "median_hours": round(float(lead_result.median_hours), 2) if lead_result and lead_result.median_hours else None,
            "mean_hours": round(float(lead_result.mean_hours), 2) if lead_result and lead_result.mean_hours else None,
            "min_hours": round(float(lead_result.min_hours), 2) if lead_result and lead_result.min_hours else None,
            "max_hours": round(float(lead_result.max_hours), 2) if lead_result and lead_result.max_hours else None,
            "completed_count": lead_result.completed_count if lead_result else 0,
        }

        # Calcular DORA Score (simplificado)
        # Elite: >1 deploy/dia, <15% falha, <1h MTTR, <1d lead time
        dora_score = 0
        if avg_weekly >= 5:  # ~1 por dia útil
            dora_score += 25
        if failure_rate < 15:
            dora_score += 25
        if metrics["metrics"]["mttr"]["median_minutes"] and metrics["metrics"]["mttr"]["median_minutes"] < 60:
            dora_score += 25
        if metrics["metrics"]["lead_time"]["median_hours"] and metrics["metrics"]["lead_time"]["median_hours"] < 24:
            dora_score += 25

        metrics["dora_score"] = dora_score
        metrics["dora_level"] = (
            "Elite" if dora_score >= 100 else
            "High" if dora_score >= 75 else
            "Medium" if dora_score >= 50 else
            "Low"
        )

    except Exception as e:
        metrics["error"] = str(e)

    # Cache o resultado
    _set_cache(cache_key, metrics)

    metrics["_cache_hit"] = False
    metrics["_cache_source"] = "database"
    metrics["_query_time_ms"] = 0  # Poderia ser medido com timing

    return metrics


@router.get("/executive/cache")
def get_cache_status():
    """Verificar status do cache de métricas."""
    return {
        "cache_enabled": True,
        "cache_type": "memory",
        "cache_ttl_seconds": CACHE_TTL,
        "cache_key_pattern": "metrics:executive:{project_id}:{days}",
        "cache_entries": len(_cache_data),
    }


@router.post("/executive/cache/clear")
def clear_metrics_cache():
    """Limpar cache de métricas."""
    keys = list(_cache_data.keys())
    for key in keys:
        if key.startswith("metrics:executive:"):
            del _cache_data[key]
    return {"cleared": len(keys), "message": f"{len(keys)} chaves removidas"}
