"""Workspace (estilo VS Code): explorer, editor e alterações do checkout.

Só GET. A lista vem do git e passa pelos bloqueios de services/workspace;
o envio de tarefas ao modelo local continua nas rotas POST da Bancada.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services import workspace

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
