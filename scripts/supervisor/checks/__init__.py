"""Checks determinísticos.

Cada módulo expõe duas funções:

    coletar(leitor, agora) -> list[Fato]   # consulta a fonte e delega
    avaliar(linhas, agora) -> list[Fato]   # lógica pura, sem I/O

A separação existe para que a lógica — limiares, buckets, severidade — seja
testável com fixtures sintéticas, sem banco. Só `coletar` conhece SQL.
"""

from __future__ import annotations

from . import critical_stalled, plan_without_execution


REGISTRO = {
    "critical_stalled": critical_stalled,
    "plan_without_execution": plan_without_execution,
}

__all__ = ["REGISTRO", "critical_stalled", "plan_without_execution"]
