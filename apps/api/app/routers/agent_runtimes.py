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
async def list_agent_runtimes(
    refresh: bool = Query(
        False,
        description="Ignora o cache de 10s e sonda os endpoints agora",
    ),
    db: Session = Depends(get_db),
):
    health = await agent_runtimes.check_all(refresh=refresh)
    active = _active_runs_by_agent(db)

    runtimes = []

    for runtime in agent_runtimes.RUNTIMES:
        payload = agent_runtimes.describe(runtime)
        payload.update(health[runtime.id].as_dict())
        payload["active_run_id"] = active.get(runtime.id)
        payload["busy"] = runtime.id in active
        runtimes.append(payload)

    return {"runtimes": runtimes}
