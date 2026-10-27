"""Check: issues não resolvidas no GlitchTip do backend (workdev-api)."""

from __future__ import annotations

from ..contexto import Contexto
from ..readers import glitchtip
from ...supervisor.modelo import Fato
from . import _comum


NOME = "backend_errors"
PROJETO = "workdev-api"


def coletar(contexto: Contexto) -> list[Fato]:
    issues = glitchtip.issues_nao_resolvidas(PROJETO)
    return _comum.avaliar(PROJETO, NOME, issues, contexto.agora)
