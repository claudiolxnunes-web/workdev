"""Chamado pelo OnFailure do systemd quando a execução termina em erro.

Mesmo raciocínio do scripts.supervisor.entrega.avisar_falha_de_execucao:
sem isto, uma falha vira silêncio, e silêncio é indistinguível de "nenhum
erro novo".
"""

from __future__ import annotations

import sys

from . import config
from ..supervisor.entrega import enviar


def avisar_falha_de_execucao(detalhe: str = "") -> None:
    texto = (
        f"⚠️ {config.PREFIXO_TELEGRAM}: execução falhou.\n"
        "Verificar: journalctl -u workdev-quality-supervisor -n 50"
    )
    if detalhe:
        texto += f"\n{detalhe[:200]}"
    resultado = enviar(texto, caminho_env=config.ALERTA_ENV_FILE)
    print(f"delivery={resultado.estado}")


if __name__ == "__main__":  # pragma: no cover — alvo do OnFailure
    avisar_falha_de_execucao(" ".join(sys.argv[1:]))
