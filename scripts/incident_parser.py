#!/usr/bin/env python3
"""
Integrar parser de incidentes do supervisor com persistência no banco.

Este script é executado pelo supervisor para:
1. Ler o status.json do agents-healthcheck
2. Detectar incidentes (serviços offline, degradados)
3. Persistir eventos incident_detected / incident_resolved no banco
4. Calcular MTTR quando incidente é resolvido

Saída: métricas em formato chave=valor para journald
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Configuração
LOG_TAG = "incident-parser"
STATE_FILE = Path("/var/lib/agents-healthcheck/status.json")
API_URL = os.environ.get("INCIDENT_API_URL", "http://127.0.0.1:8000")
API_KEY_FILE = Path("/etc/workdev-deploy/api.key")
STATE_DIR = Path("/var/lib/incident-parser")

# Serviços críticos mapeados para project_id
CRITICAL_SERVICES = {
    "workdev-api": "workdev-core",
    "agente-api": "agente-pessoal",
    "openclaw": "openclaw",
    "postgres": "infrastructure",
    "traefik": "infrastructure",
}

# Thresholds
OFFLINE_THRESHOLD = 2  # Execuções consecutivas offline para gerar incidente
RECOVERY_THRESHOLD = 2  # Execuções consecutivas online para resolver


def load_agent_status() -> dict[str, Any]:
    """Carregar status dos agentes."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception as e:
        print(f"[{LOG_TAG}] ERROR: Failed to load status.json: {e}", file=sys.stderr)
        return {}


def load_previous_state() -> dict[str, Any]:
    """Carregar estado anterior para detecção de transição."""
    state_file = STATE_DIR / "previous_state.json"
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text())
    except Exception:
        return {}


def save_previous_state(state: dict[str, Any]) -> None:
    """Salvar estado atual como anterior para próxima execução."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / "previous_state.json"
    temp_file = state_file.with_name(f".{state_file.name}.tmp")
    temp_file.write_text(json.dumps(state, indent=2))
    temp_file.rename(state_file)


def persist_incident_event(
    event_type: str,
    project_id: str,
    detected_at: str | None = None,
    resolved_at: str | None = None,
    service_name: str | None = None,
    incident_id: str | None = None,
) -> bool:
    """
    Persistir evento de incidente via API.

    POST /api/agent-runs/{run_id}/events
    Ou diretamente na tabela agent_run_events
    """
    api_key = None
    if API_KEY_FILE.exists():
        api_key = API_KEY_FILE.read_text().strip()

    # Criar payload do evento
    payload = {
        "event_type": event_type,
        "payload": {
            "project_id": project_id,
            "service_name": service_name,
            "incident_id": incident_id,
        }
    }

    if event_type == "incident_detected":
        payload["payload"]["detected_at"] = detected_at
    elif event_type == "incident_resolved":
        payload["payload"]["detected_at"] = detected_at
        payload["payload"]["resolved_at"] = resolved_at

    # Enviar para API
    url = f"{API_URL}/api/incidents"
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-API-Key": api_key or "",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except Exception as e:
        print(f"[{LOG_TAG}] ERROR: Failed to persist incident: {e}", file=sys.stderr)
        return False


def detect_incidents(current_status: dict[str, Any], previous_state: dict[str, Any]) -> list[dict]:
    """
    Detectar incidentes comparando estado atual com anterior.

    Retorna lista de incidentes detectados.
    """
    incidents = []
    now = datetime.now(timezone.utc).isoformat()

    for agent, health in current_status.items():
        service_name = agent
        current_state = health.get("status", "unknown")
        previous_health = previous_state.get(agent, {})
        previous_state_status = previous_health.get("status", "unknown")

        # Contador de falhas consecutivas
        consecutive_failures = previous_health.get("consecutive_failures", 0)
        consecutive_successes = previous_health.get("consecutive_successes", 0)

        # Atualizar contadores
        if current_state in ("offline", "blocked"):
            consecutive_failures += 1
            consecutive_successes = 0
        else:
            consecutive_successes += 1
            consecutive_failures = 0

        # Detectar incidente (transição para offline/blocked)
        if current_state in ("offline", "blocked") and consecutive_failures >= OFFLINE_THRESHOLD:
            # Verificar se já não existe incidente ativo
            incident_key = f"incident_{agent}"
            if incident_key not in previous_state:
                project_id = CRITICAL_SERVICES.get(service_name, "unknown")
                incidents.append({
                    "type": "incident_detected",
                    "agent": agent,
                    "project_id": project_id,
                    "service_name": service_name,
                    "detected_at": now,
                    "incident_id": f"inc-{agent}-{int(datetime.now(timezone.utc).timestamp())}",
                })
                print(f"[{LOG_TAG}] INCIDENT_DETECTED: {agent} ({current_state})")

        # Detectar resolução (transição para idle/healthy)
        elif current_state in ("idle", "healthy", "busy"):
            incident_key = f"incident_{agent}"
            if incident_key in previous_state:
                # Resolver incidente
                incident_data = previous_state[incident_key]
                incidents.append({
                    "type": "incident_resolved",
                    "agent": agent,
                    "project_id": CRITICAL_SERVICES.get(service_name, "unknown"),
                    "service_name": service_name,
                    "detected_at": incident_data.get("detected_at"),
                    "resolved_at": now,
                    "incident_id": incident_data.get("incident_id"),
                })
                print(f"[{LOG_TAG}] INCIDENT_RESOLVED: {agent}")

    return incidents


def main() -> int:
    """Executar parser de incidentes."""
    started_at = datetime.now(timezone.utc)
    print(f"[{LOG_TAG}] started_at={started_at.isoformat()}")

    # Carregar estados
    current_status = load_agent_status()
    previous_state = load_previous_state()

    if not current_status:
        print(f"[{LOG_TAG}] No agent status available")
        return 0

    # Detectar incidentes
    incidents = detect_incidents(current_status, previous_state)

    # Persistir incidentes
    persisted = 0
    for incident in incidents:
        event_type = incident["type"]
        kwargs = {
            "event_type": event_type,
            "project_id": incident["project_id"],
            "service_name": incident["service_name"],
        }

        if event_type == "incident_detected":
            kwargs["detected_at"] = incident["detected_at"]
            kwargs["incident_id"] = incident["incident_id"]
        elif event_type == "incident_resolved":
            kwargs["detected_at"] = incident["detected_at"]
            kwargs["resolved_at"] = incident["resolved_at"]
            kwargs["incident_id"] = incident["incident_id"]

        if persist_incident_event(**kwargs):
            persisted += 1

    print(f"[{LOG_TAG}] incidents_detected={len(incidents)}")
    print(f"[{LOG_TAG}] incidents_persisted={persisted}")

    # Atualizar estado com contadores e incidentes ativos
    new_state = {}
    for agent, health in current_status.items():
        previous_health = previous_state.get(agent, {})
        current_state = health.get("status", "unknown")

        # Atualizar contadores
        if current_state in ("offline", "blocked"):
            new_state[agent] = {
                "status": current_state,
                "consecutive_failures": previous_health.get("consecutive_failures", 0) + 1,
                "consecutive_successes": 0,
            }
        else:
            new_state[agent] = {
                "status": current_state,
                "consecutive_failures": 0,
                "consecutive_successes": previous_health.get("consecutive_successes", 0) + 1,
            }

        # Manter incidente ativo no estado
        incident_key = f"incident_{agent}"
        if incident_key in previous_state and current_state not in ("idle", "healthy", "busy"):
            new_state[incident_key] = previous_state[incident_key]
        elif current_state in ("offline", "blocked") and incident_key not in previous_state:
            # Novo incidente
            new_state[incident_key] = {
                "detected_at": started_at.isoformat(),
                "incident_id": f"inc-{agent}-{int(started_at.timestamp())}",
            }

    # Salvar estado
    save_previous_state(new_state)

    return 0 if persisted == len(incidents) else 1


if __name__ == "__main__":
    sys.exit(main())
