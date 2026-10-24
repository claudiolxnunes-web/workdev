"""Leitura do Postgres do RAG (container próprio, porta 5433).

Fonte opcional: se estiver fora do ar, o check degrada e a execução segue.
Marcar 104 documentos como "sumiram do índice" porque o container caiu seria
pior que não checar — é a mesma precaução que o `roots_unavailable` do
ingestor toma do outro lado.
"""

from __future__ import annotations

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .. import config
from ..modelo import LeituraIndisponivel


SQL_DOCUMENTOS = """
SELECT fonte_id,
       titulo,
       metadados->>'tipo' AS tipo,
       conteudo_hash,
       atualizado_em
  FROM documentos
 WHERE fonte = %(fonte)s
"""


class LeitorRag:
    """Context manager somente leitura sobre o índice do RAG."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or dsn_rag()
        self._conexao: psycopg.Connection | None = None

    def __enter__(self) -> "LeitorRag":
        try:
            self._conexao = psycopg.connect(
                self._dsn,
                autocommit=True,
                row_factory=dict_row,
                options="-c default_transaction_read_only=on",
                connect_timeout=config.TIMEOUT_CONEXAO_SEGUNDOS,
                application_name=config.APPLICATION_NAME,
            )
        except Exception as erro:  # noqa: BLE001
            raise LeituraIndisponivel(f"rag:{type(erro).__name__}") from erro
        return self

    def __exit__(self, *_excecao: object) -> None:
        if self._conexao is not None:
            self._conexao.close()
            self._conexao = None

    def consultar(self, sql: str, parametros: dict[str, Any] | None = None) -> list[dict]:
        if self._conexao is None:
            raise RuntimeError("LeitorRag usado fora do context manager")
        try:
            with self._conexao.cursor() as cursor:
                cursor.execute(sql, parametros or {})
                return list(cursor.fetchall())
        except psycopg.errors.UndefinedTable as erro:
            raise LeituraIndisponivel("rag:schema_ausente") from erro

    def documentos(self) -> list[dict]:
        return self.consultar(SQL_DOCUMENTOS, {"fonte": config.RAG_FONTE})


def dsn_rag() -> str:
    """DSN do índice, montado como o ingestor monta o dele.

    A senha vem de /opt/rag-postgres/.env — arquivo de outro projeto, lido por
    caminho explícito e nunca ecoado. `SUPERVISOR_RAG_DSN` permite apontar
    para outro banco em teste.
    """
    if os.environ.get("SUPERVISOR_RAG_DSN"):
        return os.environ["SUPERVISOR_RAG_DSN"]

    valores: dict[str, str] = {}
    try:
        for linha_bruta in config.RAG_ENV_FILE.read_text(encoding="utf-8").splitlines():
            linha = linha_bruta.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            chave, _, valor = linha.partition("=")
            valores[chave.strip()] = valor.strip().strip('"').strip("'")
    except OSError as erro:
        raise LeituraIndisponivel("rag:env_ilegivel") from erro

    senha = valores.get("POSTGRES_PASSWORD") or valores.get("RAG_PASSWORD")
    if not senha:
        raise LeituraIndisponivel("rag:senha_ausente")

    usuario = valores.get("POSTGRES_USER") or valores.get("RAG_USER") or "rag"
    banco = valores.get("POSTGRES_DB") or valores.get("RAG_DB") or "rag"
    return f"postgresql://{usuario}:{senha}@{config.RAG_HOST}:{config.RAG_PORTA}/{banco}"
