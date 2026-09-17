"""Contexto de uma execução do Quality Supervisor.

Mais simples que o do supervisor de processo: não há banco a abrir, o único
recurso é o horário da execução -- os checks chamam o reader do GlitchTip
diretamente.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Contexto:
    agora: datetime
