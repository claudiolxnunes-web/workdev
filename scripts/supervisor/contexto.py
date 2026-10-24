"""Contexto de uma execução: as fontes que os checks podem consultar.

Cada check declara de que fonte precisa pedindo-a ao contexto. Fontes caras
ou opcionais (o Postgres do RAG) abrem sob demanda e só uma vez por execução:
um check que não usa o RAG não paga por ele estar fora do ar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config
from .readers.db_rag import LeitorRag
from .readers.repo import LeitorRepositorio


@dataclass
class Contexto:
    agora: datetime
    workdev: Any = None
    raiz: Path = field(default_factory=lambda: config.WORKDEV_DIR)
    estado_agentes: Path | None = None
    _repo: LeitorRepositorio | None = field(default=None, repr=False)
    _rag: LeitorRag | None = field(default=None, repr=False)

    def repo(self) -> LeitorRepositorio:
        if self._repo is None:
            self._repo = LeitorRepositorio(self.raiz)
        return self._repo

    def rag(self) -> LeitorRag:
        """Abre o índice do RAG na primeira vez que alguém precisar dele.

        Levanta LeituraIndisponivel se o container estiver fora do ar — o
        check que pediu degrada, os outros seguem.
        """
        if self._rag is None:
            self._rag = LeitorRag().__enter__()
        return self._rag

    def fechar(self) -> None:
        if self._rag is not None:
            self._rag.__exit__(None, None, None)
            self._rag = None
