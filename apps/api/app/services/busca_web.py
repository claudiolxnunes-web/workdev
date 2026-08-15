"""
Busca web via Tavily.

Modulo isolado de proposito: o router da API, o agente pessoal do Telegram
e um eventual servidor MCP importam `buscar()` diretamente, sem duplicar
a chamada HTTP nem a leitura da chave.

Chave: TAVILY_API_KEY no .env (lida no start do processo).
Cota do plano Researcher: 1000 creditos/mes.
"""

import os
from typing import Literal

import requests

TAVILY_URL = "https://api.tavily.com/search"
TIMEOUT = 30


class BuscaWebError(RuntimeError):
    """Falha ao consultar a Tavily."""


def _chave() -> str:
    chave = os.getenv("TAVILY_API_KEY")
    if not chave:
        raise BuscaWebError("TAVILY_API_KEY nao configurada no .env")
    return chave


def buscar(
    pergunta: str,
    limite: int = 5,
    profundidade: Literal["basic", "advanced"] = "basic",
    dominios: list[str] | None = None,
    com_resposta: bool = False,
) -> dict:
    """
    Consulta a web e devolve resultados normalizados.

    pergunta      texto da consulta
    limite        quantos resultados (1-10)
    profundidade  'basic' custa 1 credito, 'advanced' custa 2 e le mais fundo
    dominios      restringe a estes dominios, ex. ['docs.python.org']
    com_resposta  pede tambem um resumo gerado pela Tavily

    Retorna:
      {
        "pergunta": str,
        "resposta": str | None,
        "resultados": [{"titulo", "url", "trecho", "score"}, ...]
      }
    """
    pergunta = (pergunta or "").strip()
    if not pergunta:
        raise BuscaWebError("pergunta vazia")

    limite = max(1, min(int(limite), 10))

    payload = {
        "api_key": _chave(),
        "query": pergunta,
        "max_results": limite,
        "search_depth": profundidade,
        "include_answer": bool(com_resposta),
    }
    if dominios:
        payload["include_domains"] = dominios

    try:
        resposta = requests.post(TAVILY_URL, json=payload, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise BuscaWebError(f"falha de rede ao consultar a Tavily: {e}") from e

    if resposta.status_code == 401:
        raise BuscaWebError("TAVILY_API_KEY rejeitada (401)")
    if resposta.status_code == 429:
        raise BuscaWebError("cota da Tavily esgotada (429)")
    if resposta.status_code != 200:
        raise BuscaWebError(f"Tavily HTTP {resposta.status_code}: {resposta.text[:200]}")

    dados = resposta.json()

    return {
        "pergunta": pergunta,
        "resposta": dados.get("answer"),
        "resultados": [
            {
                "titulo": r.get("title", ""),
                "url": r.get("url", ""),
                "trecho": r.get("content", ""),
                "score": r.get("score"),
            }
            for r in dados.get("results", [])
        ],
    }


def formatar_texto(resultado: dict) -> str:
    """Formata o retorno de buscar() para leitura em terminal ou Telegram."""
    linhas = []
    if resultado.get("resposta"):
        linhas.append(resultado["resposta"])
        linhas.append("")
    for i, r in enumerate(resultado.get("resultados", []), 1):
        linhas.append(f"{i}. {r['titulo']}")
        linhas.append(f"   {r['url']}")
        if r.get("trecho"):
            trecho = " ".join(r["trecho"].split())[:200]
            linhas.append(f"   {trecho}...")
        linhas.append("")
    return "\n".join(linhas) if linhas else "Nenhum resultado."
