"""Status operacional dos runtimes Ollama locais/GPU.

A UI consome só este endpoint: nunca fala com o Ollama diretamente e nunca
recebe URL ou token. Endpoint indisponível vira estado, não erro — a página de
Agents continua funcionando com os demais agentes.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.handoff import AgentRun
from app.services import agent_runtimes
from app.services.handoff import ACTIVE_RUN_STATUSES


router = APIRouter(prefix="/api/agent-runtimes", tags=["agents"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _active_runs_by_agent(db: Session) -> dict[str, str]:
    rows = (
        db.query(AgentRun)
        .filter(
            AgentRun.agent.in_(sorted(agent_runtimes.OLLAMA_AGENT_IDS)),
            AgentRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .all()
    )
    return {row.agent: str(row.id) for row in rows}


@router.get("")
def list_agent_runtimes(refresh: bool = False):
    # Compatibility for older clients: refresh rereads the consolidated file.
    # Physical probes belong exclusively to the central collector.
    from app.services.agent_snapshot import read_snapshot
    snapshot = read_snapshot([runtime.id for runtime in agent_runtimes.RUNTIMES])
    rows = {row['agent']: row for row in snapshot['agents']}
    runtimes = []
    for runtime in agent_runtimes.RUNTIMES:
        row = rows[runtime.id]
        physical = row.get('lifecycle') or {}
        payload = agent_runtimes.describe(runtime)
        payload.update(row)
        configured = payload['configured'] and bool(payload['model'])
        payload.update(status=('unconfigured' if not configured else 'online' if row['runtime_state'] == 'ONLINE' else 'offline'),
            status_label=row['runtime_state'] if configured else 'Não configurado', reason=row['reason'],
            busy=row['activity_state'] == 'BUSY',
            dispatchable=configured and row['runtime_state'] == 'ONLINE', latency_ms=None,
            models=[physical['model']] if physical.get('model_loaded') and physical.get('model') else [])
        runtimes.append(payload)
    return {'runtimes': runtimes, 'updated_at': snapshot['updated_at'],
        'source': 'status.json', 'probe_requested': False}
