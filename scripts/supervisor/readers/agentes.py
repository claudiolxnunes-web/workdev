"""Leitura do estado dos agentes CLI.

O Supervisor **consome** o `status.json` produzido por
`scripts/agents_healthcheck.py`. Não abre sessão tmux, não captura painel, não
reinicia nada e não reimplementa a classificação. Duplicar aquele healthcheck
seria o maior risco de duplicação arquitetural do projeto.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import config
from ..modelo import LeituraIndisponivel


def ler_estado(caminho: Path | None = None) -> dict[str, Any]:
    """Devolve o payload do healthcheck.

    Arquivo ausente ou ilegível é indisponibilidade, não "todos offline": o
    Supervisor não pode inventar diagnóstico de agente a partir da falta de
    informação. O envelhecimento do arquivo é avaliado pelo check, porque é
    justamente esse o sinal mais valioso.
    """
    alvo = Path(caminho or config.AGENTS_STATUS_FILE)
    try:
        dados = json.loads(alvo.read_text(encoding="utf-8"))
    except FileNotFoundError as erro:
        raise LeituraIndisponivel("agentes:status_ausente") from erro
    except (OSError, ValueError, json.JSONDecodeError) as erro:
        raise LeituraIndisponivel("agentes:status_ilegivel") from erro

    if not isinstance(dados, dict) or not isinstance(dados.get("agents"), dict):
        raise LeituraIndisponivel("agentes:status_invalido")
    return dados
