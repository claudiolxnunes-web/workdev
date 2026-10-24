"""Busca semântica read-only no RAG externo do WorkDev.

O índice vive em PostgreSQL/pgvector separado, normalmente na porta 5433.
Este módulo:

- gera a consulta com o mesmo modelo usado pelo ingestor;
- conecta ao RAG com transação forçada como somente leitura;
- nunca grava no índice;
- nunca expõe a senha/DSN em respostas ou logs;
- retorna evidência auditável: fonte_id, título, metadados, trecho e score.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psycopg
from openai import OpenAI
from psycopg.rows import dict_row


RAG_ENV_FILE = Path(os.getenv("RAG_ENV_FILE", "/opt/rag-postgres/.env"))
RAG_HOST = os.getenv("RAG_HOST", "127.0.0.1")
RAG_PORT = int(os.getenv("RAG_PORT", "5433"))
RAG_SOURCE = os.getenv("RAG_SOURCE", "workdev")

EMBEDDING_MODEL = "text-embedding-3-small"
MAX_QUERY_CHARS = 24_000
DEFAULT_LIMIT = 8
MAX_LIMIT = 20
SNIPPET_CHARS = 1_500

APPLICATION_NAME = "workdev-api-rag-search"


class RagSearchUnavailable(RuntimeError):
    """RAG externo indisponível ou configuração inválida."""


def _dsn() -> str:
    override = os.getenv("WORKDEV_RAG_DSN")
    if override:
        return override

    valores: dict[str, str] = {}

    try:
        for linha_bruta in RAG_ENV_FILE.read_text(encoding="utf-8").splitlines():
            linha = linha_bruta.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue

            chave, _, valor = linha.partition("=")
            valores[chave.strip()] = valor.strip().strip('"').strip("'")
    except OSError as erro:
        raise RagSearchUnavailable("rag:env_ilegivel") from erro

    senha = valores.get("POSTGRES_PASSWORD") or valores.get("RAG_PASSWORD")
    if not senha:
        raise RagSearchUnavailable("rag:senha_ausente")

    usuario = (
        valores.get("POSTGRES_USER")
        or valores.get("RAG_USER")
        or "rag"
    )
    banco = (
        valores.get("POSTGRES_DB")
        or valores.get("RAG_DB")
        or "rag"
    )

    return (
        f"postgresql://{usuario}:{senha}"
        f"@{RAG_HOST}:{RAG_PORT}/{banco}"
    )


def _embedding(texto: str) -> list[float]:
    chave = os.getenv("OPENAI_API_KEY")
    if not chave:
        raise RagSearchUnavailable("rag:openai_api_key_ausente")

    texto = texto.strip()
    if not texto:
        raise ValueError("consulta RAG vazia")

    texto = texto[:MAX_QUERY_CHARS]

    try:
        cliente = OpenAI(
            api_key=chave,
            timeout=float(os.getenv("RAG_EMBEDDING_TIMEOUT", "60")),
            max_retries=int(os.getenv("AI_PROVIDER_MAX_RETRIES", "0")),
        )
        resposta = cliente.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texto,
        )
        return resposta.data[0].embedding
    except Exception as erro:
        raise RagSearchUnavailable(
            f"rag:embedding:{type(erro).__name__}"
        ) from erro


def _vector_literal(vetor: list[float]) -> str:
    """Serializa o vetor para cast explícito ::vector no PostgreSQL."""
    return "[" + ",".join(str(float(valor)) for valor in vetor) + "]"


def search(
    termo: str,
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """Busca semanticamente no índice RAG do WorkDev."""

    termo = (termo or "").strip()
    if not termo:
        raise ValueError("termo é obrigatório")

    limit = max(1, min(int(limit), MAX_LIMIT))

    vetor = _vector_literal(_embedding(termo))

    sql = """
        SELECT
            fonte,
            fonte_id,
            titulo,
            metadados,
            LEFT(conteudo, %(snippet_chars)s) AS conteudo,
            1 - (embedding <=> %(query_vector)s::vector) AS score,
            atualizado_em
        FROM documentos
        WHERE fonte = %(fonte)s
          AND embedding IS NOT NULL
        ORDER BY embedding <=> %(query_vector)s::vector
        LIMIT %(limite)s
    """

    try:
        with psycopg.connect(
            _dsn(),
            autocommit=True,
            row_factory=dict_row,
            options="-c default_transaction_read_only=on",
            connect_timeout=5,
            application_name=APPLICATION_NAME,
        ) as conexao:
            with conexao.cursor() as cursor:
                cursor.execute(
                    sql,
                    {
                        "fonte": RAG_SOURCE,
                        "query_vector": vetor,
                        "snippet_chars": SNIPPET_CHARS,
                        "limite": limit,
                    },
                )
                rows = list(cursor.fetchall())
    except Exception as erro:
        raise RagSearchUnavailable(
            f"rag:consulta:{type(erro).__name__}"
        ) from erro

    resultados: list[dict[str, Any]] = []

    for row in rows:
        resultados.append(
            {
                "fonte": row["fonte"],
                "fonte_id": row["fonte_id"],
                "titulo": row["titulo"],
                "metadados": row["metadados"] or {},
                "conteudo": row["conteudo"],
                "score": round(float(row["score"]), 4),
                "atualizado_em": (
                    row["atualizado_em"].isoformat()
                    if row["atualizado_em"]
                    else None
                ),
            }
        )

    return resultados
