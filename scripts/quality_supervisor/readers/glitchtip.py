"""Leitura somente-leitura da API do GlitchTip.

Compatível com o protocolo de API do Sentry (endpoint /api/0/...). O token
tem escopo project:read + event:read -- não pode resolver, ignorar nem
comentar issue, só listar.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .. import config
from ...supervisor.modelo import LeituraIndisponivel


def _token() -> str:
    try:
        for linha in config.ENV_FILE.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha.startswith("GLITCHTIP_API_TOKEN="):
                return linha.split("=", 1)[1].strip()
    except OSError as erro:
        raise LeituraIndisponivel("glitchtip:env_ausente") from erro
    raise LeituraIndisponivel("glitchtip:token_ausente")


def issues_nao_resolvidas(project_slug: str) -> list[dict[str, Any]]:
    """Lista issues com status unresolved de um projeto, mais recentes primeiro.

    Uma falha de rede ou de auth degrada o check que pediu, não derruba a
    execução inteira -- mesmo contrato dos outros readers opcionais.
    """
    token = _token()
    query = urllib.parse.urlencode({"query": "is:unresolved", "limit": "100"})
    url = (
        f"{config.GLITCHTIP_BASE_URL}/api/0/projects/"
        f"{config.GLITCHTIP_ORG}/{project_slug}/issues/?{query}"
    )
    requisicao = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(
            requisicao, timeout=config.GLITCHTIP_TIMEOUT_SEGUNDOS
        ) as resposta:
            corpo = resposta.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as erro:
        raise LeituraIndisponivel(f"glitchtip:{type(erro).__name__}") from erro

    try:
        dados = json.loads(corpo)
    except ValueError as erro:
        raise LeituraIndisponivel("glitchtip:resposta_invalida") from erro

    if not isinstance(dados, list):
        raise LeituraIndisponivel("glitchtip:formato_inesperado")
    return dados
