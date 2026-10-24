#!/usr/bin/env python3
"""Servidor MCP do Backlog do WorkDev.

Expoe o Backlog Engine como ferramentas MCP. Nao fala com o Postgres:
tudo passa pela API em /api/backlog, que ja tem validacao e Alembic.

Transporte: HTTP em 127.0.0.1 (streamable-http).
"""

import os
import sys
import time

import requests
from fastmcp import FastMCP

ENV = "/opt/workdev/apps/api/.env"
BASE = os.environ.get("WORKDEV_API_URL", "http://127.0.0.1:8000")
TIMEOUT = 20


def _carregar_env(caminho=ENV):
    """Le o .env sem depender de python-dotenv."""
    dados = {}
    try:
        with open(caminho, "r", encoding="utf-8") as fh:
            for linha in fh:
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, _, valor = linha.partition("=")
                dados[chave.strip()] = valor.strip().strip('"').strip("'")
    except OSError as erro:
        print(f"[mcp] aviso: nao li {caminho}: {erro}", file=sys.stderr)
    return dados


_ENV = _carregar_env()
API_KEY = os.environ.get("WORKDEV_API_KEY") or _ENV.get("WORKDEV_API_KEY", "")
if not API_KEY:
    print("[mcp] aviso: WORKDEV_API_KEY vazia; a API deve recusar.", file=sys.stderr)

SESSAO = requests.Session()
SESSAO.headers.update({"X-API-Key": API_KEY, "Content-Type": "application/json"})

mcp = FastMCP("workdev-backlog")

# cache slug -> uuid, com validade de 10 min
_CACHE = {}
_TTL = 600


class ErroAPI(RuntimeError):
    pass


def _chamar(metodo, rota, **kw):
    url = f"{BASE}{rota}"
    try:
        resp = SESSAO.request(metodo, url, timeout=TIMEOUT, **kw)
    except requests.RequestException as erro:
        raise ErroAPI(f"WorkDev inacessivel em {url}: {erro}") from erro
    if resp.status_code == 401:
        raise ErroAPI("401: WORKDEV_API_KEY invalida ou ausente.")
    if resp.status_code == 404:
        raise ErroAPI(f"404: nao encontrado em {rota}")
    if resp.status_code >= 400:
        raise ErroAPI(f"{resp.status_code}: {resp.text[:300]}")
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {"texto": resp.text[:500]}


def _uuid_do_slug(slug):
    """Resolve slug -> project_id. O POST exige uuid; o GET usa slug."""
    agora = time.time()
    achado = _CACHE.get(slug)
    if achado and agora - achado[1] < _TTL:
        return achado[0]
    dados = _chamar("GET", f"/api/projects/{slug}")
    projeto_id = dados.get("id") if isinstance(dados, dict) else None
    if not projeto_id:
        raise ErroAPI(f"projeto '{slug}' sem campo id na resposta: {str(dados)[:200]}")
    _CACHE[slug] = (projeto_id, agora)
    return projeto_id


def _resumir(item):
    """Uma linha legivel por item de backlog."""
    if not isinstance(item, dict):
        return str(item)
    partes = [
        str(item.get("id", ""))[:8],
        f"[{item.get('status', '?')}]",
        f"({item.get('priority', '?')})",
        item.get("title", "sem titulo"),
    ]
    dono = item.get("owner")
    if dono:
        partes.append(f"- {dono}")
    return " ".join(partes)


@mcp.tool()
def registrar_pendencia(
    projeto: str,
    titulo: str,
    descricao: str = "",
    tipo: str = "task",
    prioridade: str = "medium",
    responsavel: str = "",
) -> str:
    """Registra uma pendencia no backlog do WorkDev.

    projeto: slug do projeto (ex.: 'feed-bpf', 'workdev').
    tipo: feature, bug, task, chore.
    prioridade: low, medium, high, critical.
    responsavel: quem toca (ex.: 'claudio', 'codex').
    """
    corpo = {
        "project_id": _uuid_do_slug(projeto),
        "title": titulo,
        "type": tipo,
        "priority": prioridade,
        "status": "todo",
    }
    if descricao:
        corpo["description"] = descricao
    if responsavel:
        corpo["owner"] = responsavel
    criado = _chamar("POST", "/api/backlog", json=corpo)
    return f"registrado: {_resumir(criado)}"


@mcp.tool()
def listar_pendencias(projeto: str, status: str = "", limite: int = 30) -> str:
    """Lista pendencias de um projeto. status filtra (todo, doing, done)."""
    itens = _chamar("GET", f"/api/backlog/{projeto}")
    if isinstance(itens, dict):
        itens = itens.get("items") or itens.get("data") or []
    if status:
        itens = [i for i in itens if str(i.get("status", "")).lower() == status.lower()]
    if not itens:
        return f"nenhuma pendencia em '{projeto}'" + (f" com status '{status}'" if status else "")
    linhas = [_resumir(i) for i in itens[:limite]]
    extra = f"\n... e mais {len(itens) - limite}" if len(itens) > limite else ""
    return f"{len(itens)} pendencia(s) em '{projeto}':\n" + "\n".join(linhas) + extra


@mcp.tool()
def concluir_pendencia(item_id: str, status: str = "done") -> str:
    """Muda o status de uma pendencia. Por padrao marca como concluida."""
    try:
        atualizado = _chamar("PATCH", f"/api/backlog/{item_id}/status", json={"status": status})
    except ErroAPI as erro:
        # algumas rotas recebem o status como query param, nao no corpo
        if "422" not in str(erro):
            raise
        atualizado = _chamar("PATCH", f"/api/backlog/{item_id}/status", params={"status": status})
    return f"atualizado: {_resumir(atualizado)}"


@mcp.tool()
def detalhar_pendencia(item_id: str) -> str:
    """Mostra as subtarefas de uma pendencia."""
    subs = _chamar("GET", f"/api/subtasks/{item_id}")
    if isinstance(subs, dict):
        subs = subs.get("items") or subs.get("data") or []
    if not subs:
        return f"pendencia {item_id[:8]} sem subtarefas"
    return f"{len(subs)} subtarefa(s):\n" + "\n".join(_resumir(s) for s in subs)


if __name__ == "__main__":
    porta = int(os.environ.get("MCP_PORT", "8787"))
    mcp.run(transport="http", host="127.0.0.1", port=porta)
