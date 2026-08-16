"""Checks determinísticos.

Cada módulo expõe duas funções:

    coletar(contexto) -> list[Fato]        # consulta as fontes e delega
    avaliar(dados, agora) -> list[Fato]    # lógica pura, sem I/O

A separação existe para que a lógica — limiares, buckets, severidade — seja
testável com fixtures sintéticas, sem banco, sem git e sem systemd. Só
`coletar` conhece fonte de dados.
"""

from __future__ import annotations

from . import (
    agent_health,
    critical_stalled,
    deploy_drift,
    knowledge_drift,
    plan_without_execution,
)


REGISTRO = {
    "critical_stalled": critical_stalled,
    "plan_without_execution": plan_without_execution,
    "deploy_drift": deploy_drift,
    "knowledge_drift": knowledge_drift,
    "agent_health": agent_health,
}

__all__ = ["REGISTRO", *sorted(REGISTRO)]
