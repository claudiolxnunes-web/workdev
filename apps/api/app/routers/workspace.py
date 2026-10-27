"""Workspace (estilo VS Code): explorer, editor e alterações do checkout.

As leituras do checkout são só GET: a lista vem do git e passa pelos bloqueios
de services/workspace; o envio de tarefas ao modelo local continua nas rotas
POST da Bancada. Os POST daqui são da sessão (services/workspace_sessao e
workspace_execucao): criam e encerram a cópia isolada, executam fatias, salvam
edições do editor nela e incorporam — nada escreve no checkout, exceto o
incorporar, que é clique do operador.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services import workspace, workspace_execucao, workspace_sessao

router = APIRouter(prefix="/workspace", tags=["workspace"])


def _chamar(funcao, *args):
    try:
        return funcao(*args)
    except workspace.WorkspaceErro as erro:
        raise HTTPException(erro.status, {"code": erro.codigo, "message": erro.mensagem}) from erro


def _raiz(sessao: str | None):
    """Com `sessao`, as leituras vêm da cópia da sessão ativa; sem, do checkout."""
    return _chamar(workspace_sessao.raiz_ativa, sessao) if sessao else None


SESSAO = Query(None, max_length=40)


@router.get("/arvore")
def arvore(pasta: str = Query("", max_length=500), sessao: str | None = SESSAO):
    return _chamar(workspace.arvore, pasta, _raiz(sessao))


@router.get("/arquivo")
def arquivo(caminho: str = Query(..., min_length=1, max_length=500), sessao: str | None = SESSAO):
    return _chamar(workspace.ler_arquivo, caminho, _raiz(sessao))


@router.get("/alteracoes")
def alteracoes(sessao: str | None = SESSAO):
    return _chamar(workspace.alteracoes, _raiz(sessao))


@router.get("/diff")
def diff(caminho: str = Query(..., min_length=1, max_length=500), sessao: str | None = SESSAO):
    return _chamar(workspace.diff_arquivo, caminho, _raiz(sessao))


# ---------------------------------------------------------------- sessão

class NovaSessao(BaseModel):
    task_id: str | None = Field(default=None, max_length=64)
    chat_session_id: str | None = Field(default=None, max_length=64)
    titulo: str | None = Field(default=None, max_length=200)


class Edicao(BaseModel):
    caminho: str = Field(min_length=1, max_length=500)
    texto: str
    sha256: str = Field(min_length=64, max_length=64)


class Encerramento(BaseModel):
    descartar_alteracoes: bool = False


@router.get("/sessao")
def sessoes():
    return _chamar(workspace_sessao.listar)


@router.post("/sessao", status_code=201)
def criar_sessao(pedido: NovaSessao):
    return _chamar(workspace_sessao.criar, pedido.task_id, pedido.chat_session_id, pedido.titulo)


class ApagarBranch(BaseModel):
    perder_commits: bool = False


# Antes de "/sessao/{ident}": senão "anteriores" vira identificador de sessão.
@router.get("/sessao/anteriores")
def sessoes_anteriores():
    return _chamar(workspace_sessao.anteriores)


@router.post("/sessao/{ident}/apagar-branch")
def apagar_branch_sessao(ident: str, pedido: ApagarBranch | None = None):
    return _chamar(workspace_sessao.apagar_branch, ident, bool(pedido and pedido.perder_commits))


@router.get("/sessao/{ident}")
def estado_sessao(ident: str):
    return _chamar(workspace_sessao.estado, ident)


@router.get("/sessao/{ident}/diff")
def diff_sessao(ident: str):
    return _chamar(workspace_sessao.diff, ident)


@router.post("/sessao/{ident}/arquivo")
def salvar_arquivo(ident: str, pedido: Edicao):
    return _chamar(workspace_sessao.salvar_arquivo, ident, pedido.caminho, pedido.texto, pedido.sha256)


@router.post("/sessao/{ident}/encerrar")
def encerrar_sessao(ident: str, pedido: Encerramento | None = None):
    return _chamar(workspace_sessao.encerrar, ident, bool(pedido and pedido.descartar_alteracoes))


# ---------------------------------------------------------------- execução

class Plano(BaseModel):
    plano: dict


class Execucao(BaseModel):
    correcao: str | None = Field(default=None, max_length=2000)


class Incorporacao(BaseModel):
    modo: str = Field(pattern="^(merge|squash)$")
    mensagem: str | None = Field(default=None, max_length=4000)


@router.get("/sessao/{ident}/medicao")
def medicao_sessao(ident: str):
    return _chamar(workspace_execucao.medicao, ident)


@router.post("/sessao/{ident}/plano")
def aprovar_plano(ident: str, pedido: Plano):
    return _chamar(workspace_execucao.aprovar_plano, ident, pedido.plano)


@router.post("/sessao/{ident}/fatias/{n}/executar")
def executar_fatia(ident: str, n: int, pedido: Execucao | None = None):
    # Erros de validação chegam como evento "erro" do próprio fluxo.
    return StreamingResponse(workspace_execucao.executar_fatia(ident, n, pedido.correcao if pedido else None),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class SqlBanco(BaseModel):
    sql: str = Field(min_length=1, max_length=4000)


class Reversao(BaseModel):
    forcar: bool = False


@router.post("/sessao/{ident}/fatias/{n}/banco/simular")
def simular_banco(ident: str, n: int, pedido: SqlBanco):
    """SQL editado pelo operador: valida e simula (rollback). Nada é gravado."""
    return _chamar(workspace_execucao.simular_banco, ident, n, pedido.sql)


@router.post("/sessao/{ident}/fatias/{n}/banco/aplicar")
def aplicar_banco(ident: str, n: int):
    """Clique do operador: grava no banco o que foi simulado."""
    return _chamar(workspace_execucao.aplicar_banco, ident, n)


@router.post("/sessao/{ident}/fatias/{n}/banco/reverter")
def reverter_banco(ident: str, n: int, pedido: Reversao | None = None):
    return _chamar(workspace_execucao.reverter_banco, ident, n, bool(pedido and pedido.forcar))


@router.post("/sessao/{ident}/fatias/{n}/pular")
def pular_fatia(ident: str, n: int):
    return _chamar(workspace_execucao.pular_fatia, ident, n)


@router.post("/sessao/{ident}/incorporar")
def incorporar(ident: str, pedido: Incorporacao):
    return _chamar(workspace_execucao.incorporar, ident, pedido.modo, pedido.mensagem)
