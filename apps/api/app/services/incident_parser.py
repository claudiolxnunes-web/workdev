"""
Parser de eventos do supervisor para detectar incidentes.

Este módulo analisa os eventos do supervisor (monitoramento de serviços)
e gera eventos de incidente quando detecta problemas de saúde na plataforma.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.handoff import AgentRun, AgentRunEvent

logger = logging.getLogger(__name__)


# Tipos de eventos de incidente
INCIDENT_DETECTED = "incident_detected"
INCIDENT_RESOLVED = "incident_resolved"
INCIDENT_ESCALATED = "incident_escalated"

# Serviços monitorados críticos
CRITICAL_SERVICES = {
    "workdev-api": "API principal do WorkDev",
    "docker": "Docker daemon",
    "postgres": "Banco de dados PostgreSQL",
    "traefik": "Proxy reverso / Load balancer",
}

# Thresholds para detecção de incidente
FAILURE_THRESHOLD = 3  # Número de falhas consecutivas para gerar incidente
RECOVERY_THRESHOLD = 2  # Número de sucessos consecutivos para considerar recuperado


class IncidentParser:
    """
    Parser para detectar incidentes a partir de eventos de monitoramento.

    Detecta:
    - Serviços críticos offline
    - Health checks falhando repetidamente
    - Latência acima do threshold
    - Deploy failures em cascata
    """

    def __init__(self, db: Session):
        self.db = db

    def parse_service_health(
        self,
        service_name: str,
        status: str,
        latency_ms: int | None = None,
        detail: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict[str, Any] | None:
        """
        Analisar saúde de um serviço e retornar dados de incidente se aplicável.

        Retorna:
        - dict com dados do incidente se detectado
        - None se status normal
        """
        timestamp = timestamp or datetime.now(timezone.utc)

        # Verificar se é serviço crítico
        is_critical = service_name in CRITICAL_SERVICES

        # Status considerado "online"
        online_statuses = {"online", "active", "running", "healthy"}
        is_offline = status.lower() not in online_statuses

        # Se está offline e é crítico, gerar incidente
        if is_offline and is_critical:
            return {
                "incident_type": "service_outage",
                "service": service_name,
                "service_description": CRITICAL_SERVICES.get(service_name),
                "status": status,
                "latency_ms": latency_ms,
                "detail": detail,
                "severity": "critical",
                "detected_at": timestamp.isoformat(),
            }

        # Verificar latência alta (threshold: 5000ms)
        if latency_ms and latency_ms > 5000:
            return {
                "incident_type": "high_latency",
                "service": service_name,
                "latency_ms": latency_ms,
                "threshold_ms": 5000,
                "severity": "warning",
                "detected_at": timestamp.isoformat(),
            }

        return None

    def parse_deploy_failure(
        self,
        proof_id: str,
        project: str,
        status: str,
        error_message: str | None = None,
        timestamp: datetime | None = None,
    ) -> dict[str, Any] | None:
        """
        Analisar falha de deploy e retornar dados de incidente se aplicável.

        Status que geram incidente:
        - DEPLOY_FAILED
        - ROLLED_BACK
        - DEPLOY_DEGRADED (apenas se persistir)
        """
        timestamp = timestamp or datetime.now(timezone.utc)

        incident_statuses = {"DEPLOY_FAILED", "ROLLED_BACK"}

        if status in incident_statuses:
            return {
                "incident_type": "deploy_failure",
                "proof_id": proof_id,
                "project": project,
                "deploy_status": status,
                "error_message": error_message,
                "severity": "high" if status == "DEPLOY_FAILED" else "medium",
                "detected_at": timestamp.isoformat(),
            }

        return None

    def create_incident_event(
        self,
        project_id: UUID,
        incident_data: dict[str, Any],
        run_id: UUID | None = None,
    ) -> AgentRunEvent:
        """
        Criar um evento de incidente no banco de dados.

        Args:
        - project_id: UUID do projeto afetado
        - incident_data: dados do incidente detectado
        - run_id: UUID do agent run relacionado (opcional)

        Returns:
        - AgentRunEvent criado
        """
        event = AgentRunEvent(
            run_id=run_id or UUID("00000000-0000-0000-0000-000000000000"),
            event_type=INCIDENT_DETECTED,
            message=f"Incidente detectado: {incident_data.get('incident_type')} em {incident_data.get('service', 'unknown')}",
            payload={
                "project_id": str(project_id),
                **incident_data,
            },
        )

        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)

        logger.info(f"Incidente registrado: {incident_data.get('incident_type')}")

        return event

    def create_resolution_event(
        self,
        incident_event_id: UUID,
        resolution_data: dict[str, Any],
        run_id: UUID | None = None,
    ) -> AgentRunEvent:
        """
        Criar um evento de resolução de incidente.

        Args:
        - incident_event_id: UUID do evento de incidente original
        - resolution_data: dados da resolução
        - run_id: UUID do agent run relacionado (opcional)

        Returns:
        - AgentRunEvent de resolução criado

        O payload sempre carrega `detected_at` (copiado do evento de
        incidente original) e `resolved_at`, porque a query de MTTR em
        GET /api/metrics/executive depende desses dois campos para
        calcular o tempo de recuperação.
        """
        detected_at = resolution_data.get("detected_at")
        if detected_at is None:
            original = self.db.query(AgentRunEvent).filter(
                AgentRunEvent.id == incident_event_id
            ).first()
            if original and isinstance(original.payload, dict):
                detected_at = original.payload.get("detected_at")

        event = AgentRunEvent(
            run_id=run_id or UUID("00000000-0000-0000-0000-000000000000"),
            event_type=INCIDENT_RESOLVED,
            message=f"Incidente resolvido: {resolution_data.get('incident_type')}",
            payload={
                **resolution_data,
                "incident_event_id": str(incident_event_id),
                "detected_at": detected_at,
                "resolved_at": resolution_data.get(
                    "resolved_at", datetime.now(timezone.utc).isoformat()
                ),
            },
        )

        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)

        logger.info(f"Resolução registrada para incidente {incident_event_id}")

        return event

    def check_and_create_incident(
        self,
        service_name: str,
        status: str,
        project_id: UUID,
        latency_ms: int | None = None,
        detail: str | None = None,
    ) -> AgentRunEvent | None:
        """
        Verificar saúde do serviço e criar incidente se necessário.

        Este é o método principal que deve ser chamado pelo supervisor.
        """
        incident_data = self.parse_service_health(
            service_name=service_name,
            status=status,
            latency_ms=latency_ms,
            detail=detail,
        )

        if incident_data:
            return self.create_incident_event(
                project_id=project_id,
                incident_data=incident_data,
            )

        return None


def parse_supervisor_output(
    db: Session,
    monitoring_result: dict[str, Any],
    project_id: UUID,
) -> list[AgentRunEvent]:
    """
    Parser principal para output do supervisor de monitoramento.

    Analisa todos os serviços monitorados e cria incidentes para os problemas detectados.

    Args:
    - db: sessão do banco de dados
    - monitoring_result: resultado do endpoint /monitoring/status
    - project_id: UUID do projeto sendo monitorado

    Returns:
    - lista de AgentRunEvent criados
    """
    parser = IncidentParser(db)
    events = []

    # Extrair serviços do resultado do monitoramento
    services = monitoring_result.get("services", [])

    for service in services:
        service_name = service.get("name", "unknown")
        status = service.get("status", "unknown")
        latency = service.get("latency_ms")
        detail = service.get("detail")

        event = parser.check_and_create_incident(
            service_name=service_name,
            status=status,
            project_id=project_id,
            latency_ms=latency,
            detail=detail,
        )

        if event:
            events.append(event)

    return events
