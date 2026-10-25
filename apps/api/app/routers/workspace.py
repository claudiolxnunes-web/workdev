"""Workspace (estilo VS Code): explorer, editor e alterações do checkout.

As leituras do checkout são só GET: a lista vem do git e passa pelos bloqueios
de services/workspace; o envio de tarefas ao modelo local continua nas rotas
POST da Bancada. Os POST daqui são da sessão (services/workspace_sessao): criam
e encerram a cópia isolada da sessão — nunca escrevem no checkout.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import workspace, workspace_sessao

router = APIRouter(prefix="/workspace", tags=["workspace"])


def _chamar(funcao, *args):
    try:
        return funcao(*args)
    except workspace.WorkspaceErro as erro:
        raise HTTPException(erro.status, {"code": erro.codigo, "message": erro.mensagem}) from erro


@router.get("/arvore")
def arvore(pasta: str = Query("", max_length=500)):
    return _chamar(workspace.arvore, pasta)


@router.get("/arquivo")
def arquivo(caminho: str = Query(..., min_length=1, max_length=500)):
    return _chamar(workspace.ler_arquivo, caminho)


@router.get("/alteracoes")
def alteracoes():
    return _chamar(workspace.alteracoes)


@router.get("/diff")
def diff(caminho: str = Query(..., min_length=1, max_length=500)):
    return _chamar(workspace.diff_arquivo, caminho)


# ---------------------------------------------------------------- sessão

class NovaSessao(BaseModel):
    task_id: str | None = Field(default=None, max_length=64)
    chat_session_id: str | None = Field(default=None, max_length=64)
    titulo: str | None = Field(default=None, max_length=200)


class Encerramento(BaseModel):
    descartar_alteracoes: bool = False


@router.get("/sessao")
def sessoes():
    return _chamar(workspace_sessao.listar)


@router.post("/sessao", status_code=201)
def criar_sessao(pedido: NovaSessao):
    return _chamar(workspace_sessao.criar, pedido.task_id, pedido.chat_session_id, pedido.titulo)


@router.get("/sessao/{ident}")
def estado_sessao(ident: str):
    return _chamar(workspace_sessao.estado, ident)


@router.get("/sessao/{ident}/diff")
def diff_sessao(ident: str):
    return _chamar(workspace_sessao.diff, ident)


@router.post("/sessao/{ident}/encerrar")
def encerrar_sessao(ident: str, pedido: Encerramento | None = None):
    return _chamar(workspace_sessao.encerrar, ident, bool(pedido and pedido.descartar_alteracoes))
