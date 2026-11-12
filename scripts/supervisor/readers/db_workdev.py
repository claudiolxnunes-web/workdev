"""Leitura do Postgres principal do WorkDev, em modo somente leitura.

A garantia de "somente leitura" não é confiança no código: a sessão abre com
`default_transaction_read_only=on`, então qualquer INSERT/UPDATE/DELETE — de
bug, de descuido ou de um check futuro mal escrito — é recusado pelo próprio
servidor com ReadOnlySqlTransaction. Isso é verificado por teste.
"""

from __future__ import annotations

import os
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

from .. import config


class LeitorWorkdev:
    """Context manager sobre uma conexão somente leitura."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or dsn_workdev()
        self._conexao: psycopg.Connection | None = None

    def __enter__(self) -> "LeitorWorkdev":
        self._conexao = psycopg.connect(
            self._dsn,
            autocommit=True,
            row_factory=dict_row,
            # Recusado pelo servidor, não pela aplicação.
            options="-c default_transaction_read_only=on",
            connect_timeout=config.TIMEOUT_CONEXAO_SEGUNDOS,
            application_name=config.APPLICATION_NAME,
        )
        return self

    def __exit__(self, *_excecao: object) -> None:
        if self._conexao is not None:
            self._conexao.close()
            self._conexao = None

    def consultar(self, sql: str, parametros: dict[str, Any] | None = None) -> list[dict]:
        if self._conexao is None:
            raise RuntimeError("LeitorWorkdev usado fora do context manager")
        with self._conexao.cursor() as cursor:
            cursor.execute(sql, parametros or {})
            return list(cursor.fetchall())


def dsn_workdev() -> str:
    """DSN do Postgres do WorkDev.

    A chave chega pelo ambiente do serviço (EnvironmentFile na unit, lido
    como root). O load_dotenv é só a rede de segurança para quem roda o
    Supervisor na mão; se o arquivo não estiver legível, a variável do
    ambiente já está no lugar.
    """
    try:
        load_dotenv(config.ENV_FILE)
    except OSError:
        pass
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(f"DATABASE_URL ausente (nem no ambiente nem em {config.ENV_FILE})")
    # SQLAlchemy usa o dialeto no esquema; libpq não entende.
    for dialeto in ("postgresql+psycopg://", "postgresql+psycopg2://"):
        url = url.replace(dialeto, "postgresql://")
    return url
