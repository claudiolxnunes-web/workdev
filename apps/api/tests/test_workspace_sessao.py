"""Sessão do Workspace: cópia isolada por sessão, uma ativa, árvore limpa, branch preservado."""
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import workspace as rota
from app.services import build_worktree, workspace, workspace_sessao as sessao
from app.services.workspace import WorkspaceErro


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    raiz = tmp_path / "repo"
    (raiz / "app").mkdir(parents=True)
    (raiz / "app" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (raiz / "node_modules").mkdir()
    (raiz / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    git(raiz.parent, "init", "-q", "-b", "main", str(raiz))
    git(raiz, "add", ".")
    git(raiz, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    monkeypatch.setattr(workspace, "REPO", raiz)
    monkeypatch.setattr(build_worktree, "BUILDS_ROOT", tmp_path / "builds")
    return raiz


def commitar(meta: dict, arquivo: str, texto: str, mensagem: str) -> None:
    cwd = Path(meta["caminho"])
    (cwd / arquivo).write_text(texto, encoding="utf-8")
    git(cwd, "add", arquivo)
    git(cwd, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", mensagem)


def test_criar_abre_worktree_no_head_com_branch_proprio(repo):
    meta = sessao.criar(task_id="t-1", chat_session_id="c-1", titulo="Validar e-mail")
    destino = Path(meta["caminho"])
    assert meta["status"] == "ativa" and meta["branch"] == f"workspace/{meta['id']}"
    assert meta["base"] == git(repo, "rev-parse", "HEAD") and meta["branch_origem"] == "main"
    assert git(destino, "rev-parse", "--abbrev-ref", "HEAD") == meta["branch"]
    assert (destino / "node_modules").is_symlink()
    assert sessao.listar()["ativa"]["id"] == meta["id"]
    # O checkout do operador não muda.
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_uma_sessao_ativa_por_vez(repo):
    sessao.criar()
    with pytest.raises(WorkspaceErro) as erro:
        sessao.criar()
    assert erro.value.codigo == "sessao_ativa"


def test_arvore_suja_bloqueia_e_nao_rastreado_nao(repo):
    (repo / "rascunho.md").write_text("x\n", encoding="utf-8")
    (repo / "app" / "mod.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    with pytest.raises(WorkspaceErro) as erro:
        sessao.criar()
    assert erro.value.codigo == "arvore_suja" and "app/mod.py" in erro.value.mensagem
    assert "rascunho.md" not in erro.value.mensagem
    git(repo, "checkout", "--", "app/mod.py")
    assert sessao.criar()["status"] == "ativa"


def test_estado_e_diff_mostram_commits_e_pendencias_sem_o_ambiente(repo):
    meta = sessao.criar()
    commitar(meta, "app/mod.py", "def f():\n    return 2\n", "fatia 1: retorna 2")
    (Path(meta["caminho"]) / "app" / "novo.py").write_text("X = 1\n", encoding="utf-8")
    estado = sessao.estado(meta["id"])
    assert [c["mensagem"] for c in estado["commits"]] == ["fatia 1: retorna 2"]
    assert estado["alteracoes"] == [{"status": "??", "caminho": "app/novo.py"}]
    d = sessao.diff(meta["id"])
    assert "+    return 2" in d["diff"] and d["nao_rastreados"] == ["app/novo.py"]


def test_encerrar_pede_confirmacao_com_pendencia_e_preserva_branch(repo):
    meta = sessao.criar()
    commitar(meta, "app/mod.py", "def f():\n    return 3\n", "fatia 1")
    (Path(meta["caminho"]) / "app" / "mod.py").write_text("lixo\n", encoding="utf-8")
    with pytest.raises(WorkspaceErro) as erro:
        sessao.encerrar(meta["id"])
    assert erro.value.codigo == "sessao_com_alteracoes"
    final = sessao.encerrar(meta["id"], descartar_alteracoes=True)
    assert final["status"] == "encerrada" and final["alteracoes_descartadas"] == 1
    assert not Path(meta["caminho"]).exists()
    assert git(repo, "branch", "--list", meta["branch"])
    # Encerrada, o histórico continua legível a partir do branch.
    assert [c["mensagem"] for c in sessao.estado(meta["id"])["commits"]] == ["fatia 1"]
    assert "+    return 3" in sessao.diff(meta["id"])["diff"]
    assert sessao.listar()["ativa"] is None
    with pytest.raises(WorkspaceErro):
        sessao.encerrar(meta["id"])


def test_diretorio_apagado_a_mao_encerra_a_sessao(repo):
    meta = sessao.criar()
    shutil.rmtree(meta["caminho"])
    assert sessao.listar()["ativa"] is None
    assert sessao.estado(meta["id"])["status"] == "encerrada"
    assert sessao.criar()["status"] == "ativa"


def test_id_invalido_e_inexistente(repo):
    for ident in ("../x", "250101-000000-zzzz"):
        with pytest.raises(WorkspaceErro) as erro:
            sessao.estado(ident)
        assert erro.value.status == 404


def test_rotas_http(repo):
    app = FastAPI()
    app.include_router(rota.router, prefix="/api")
    cliente = TestClient(app)
    criada = cliente.post("/api/workspace/sessao", json={"titulo": "x"})
    assert criada.status_code == 201
    ident = criada.json()["id"]
    assert cliente.post("/api/workspace/sessao", json={}).json()["detail"]["code"] == "sessao_ativa"
    assert cliente.get("/api/workspace/sessao").json()["ativa"]["id"] == ident
    assert cliente.get(f"/api/workspace/sessao/{ident}").json()["commits"] == []
    assert cliente.get(f"/api/workspace/sessao/{ident}/diff").json()["diff"] == ""
    assert cliente.post(f"/api/workspace/sessao/{ident}/encerrar").json()["status"] == "encerrada"


# ---------------------------------------------------------------- editor e leitura da cópia

def test_leituras_vem_da_copia_da_sessao(repo):
    meta = sessao.criar()
    commitar(meta, "app/mod.py", "def f():\n    return 5\n", "fatia 1")
    (Path(meta["caminho"]) / "app" / "novo.py").write_text("Y = 1\n", encoding="utf-8")
    copia = sessao.raiz_ativa(meta["id"])
    assert "return 5" in workspace.ler_arquivo("app/mod.py", copia)["texto"]
    assert "return 1" in workspace.ler_arquivo("app/mod.py")["texto"]
    nomes = [i["caminho"] for i in workspace.arvore("app", copia)["itens"]]
    assert "app/novo.py" in nomes and "app/novo.py" not in [i["caminho"] for i in workspace.arvore("app")["itens"]]
    assert [i["caminho"] for i in workspace.alteracoes(copia)["itens"]] == ["app/novo.py"]
    assert not any(i["caminho"].startswith("node_modules") for i in workspace.arvore("", copia)["itens"])


def test_salvar_no_editor_vira_commit_do_operador(repo):
    git(repo, "config", "user.name", "Operador")
    git(repo, "config", "user.email", "op@x")
    meta = sessao.criar()
    copia = Path(meta["caminho"])
    aberto = workspace.ler_arquivo("app/mod.py", copia)
    r = sessao.salvar_arquivo(meta["id"], "app/mod.py", "def f():\n    return 42\n", aberto["sha256"])
    assert (copia / "app" / "mod.py").read_text() == "def f():\n    return 42\n"
    assert git(copia, "log", "-1", "--format=%an|%s") == "Operador|edição manual: app/mod.py"
    assert r["commit"] == git(copia, "rev-parse", "HEAD")
    # O checkout do operador não muda.
    assert (repo / "app" / "mod.py").read_text() == "def f():\n    return 1\n"


def test_salvar_recusa_arquivo_que_mudou_copia_suja_bloqueado_e_segredo(repo):
    meta = sessao.criar()
    copia = Path(meta["caminho"])
    aberto = workspace.ler_arquivo("app/mod.py", copia)
    for texto, sha, codigo in (("x\n", "0" * 64, "arquivo_mudou"), (aberto["texto"], aberto["sha256"], "sem_mudanca")):
        with pytest.raises(WorkspaceErro) as erro:
            sessao.salvar_arquivo(meta["id"], "app/mod.py", texto, sha)
        assert erro.value.codigo == codigo
    with pytest.raises(WorkspaceErro) as erro:
        sessao.salvar_arquivo(meta["id"], ".env", "X=1\n", "0" * 64)
    assert erro.value.codigo == "caminho_bloqueado"
    commitar(meta, "app/chave.py", "TOKEN = 'sk-abcdefghijklmnop'\n", "chave")
    chave = workspace.ler_arquivo("app/chave.py", copia)
    assert chave["mascarado"] is True and "[mascarado]" in chave["texto"]
    with pytest.raises(WorkspaceErro) as erro:
        sessao.salvar_arquivo(meta["id"], "app/chave.py", chave["texto"] + "# x\n", chave["sha256"])
    assert erro.value.codigo == "arquivo_com_segredo"
    assert "sk-abcdefghijklmnop" in (copia / "app" / "chave.py").read_text()
    (copia / "app" / "mod.py").write_text("sujo\n", encoding="utf-8")
    with pytest.raises(WorkspaceErro) as erro:
        sessao.salvar_arquivo(meta["id"], "app/outro.py", "x\n", "0" * 64)
    assert erro.value.codigo == "sessao_com_alteracoes"


def test_rotas_leem_a_copia_com_sessao(repo):
    git(repo, "config", "user.name", "Operador")
    git(repo, "config", "user.email", "op@x")
    app = FastAPI()
    app.include_router(rota.router, prefix="/api")
    cliente = TestClient(app)
    meta = sessao.criar()
    commitar(meta, "app/mod.py", "def f():\n    return 8\n", "fatia")
    assert "return 8" in cliente.get("/api/workspace/arquivo", params={"caminho": "app/mod.py", "sessao": meta["id"]}).json()["texto"]
    assert "return 1" in cliente.get("/api/workspace/arquivo", params={"caminho": "app/mod.py"}).json()["texto"]
    aberto = cliente.get("/api/workspace/arquivo", params={"caminho": "app/mod.py", "sessao": meta["id"]}).json()
    salvo = cliente.post(f"/api/workspace/sessao/{meta['id']}/arquivo",
                         json={"caminho": "app/mod.py", "texto": "def f():\n    return 9\n", "sha256": aberto["sha256"]})
    assert salvo.status_code == 200
    sessao.encerrar(meta["id"])
    assert cliente.get("/api/workspace/arvore", params={"sessao": meta["id"]}).json()["detail"]["code"] == "sessao_encerrada"


# ---------------------------------------------------------------- sessões anteriores

def test_anteriores_lista_branch_preservado_e_apagar_pede_confirmacao_se_perde_commit(repo):
    meta = sessao.criar(titulo="com trabalho")
    commitar(meta, "app/mod.py", "def f():\n    return 2\n", "fatia 1")
    with pytest.raises(WorkspaceErro) as ativa:
        sessao.apagar_branch(meta["id"])
    assert ativa.value.codigo == "sessao_ativa"
    sessao.encerrar(meta["id"])
    [anterior] = sessao.anteriores()
    assert anterior["id"] == meta["id"] and anterior["nao_incorporados"] == 1
    with pytest.raises(WorkspaceErro) as perde:
        sessao.apagar_branch(meta["id"])
    assert perde.value.codigo == "commits_nao_incorporados"
    assert git(repo, "branch", "--list", meta["branch"])
    apagada = sessao.apagar_branch(meta["id"], perder_commits=True)
    assert apagada["branch_apagado_sha"] and not git(repo, "branch", "--list", meta["branch"])
    # O registro da sessão fica; ela só sai da lista de anteriores.
    assert sessao.anteriores() == [] and sessao._ler_meta(meta["id"])["status"] == "encerrada"
    with pytest.raises(WorkspaceErro) as de_novo:
        sessao.apagar_branch(meta["id"])
    assert de_novo.value.codigo == "branch_ja_apagado"


def test_apagar_branch_sem_commit_novo_dispensa_confirmacao_e_rotas(repo):
    app = FastAPI()
    app.include_router(rota.router, prefix="/api")
    cliente = TestClient(app)
    ident = cliente.post("/api/workspace/sessao", json={}).json()["id"]
    cliente.post(f"/api/workspace/sessao/{ident}/encerrar")
    lista = cliente.get("/api/workspace/sessao/anteriores").json()
    assert [s["id"] for s in lista] == [ident] and lista[0]["nao_incorporados"] == 0
    resposta = cliente.post(f"/api/workspace/sessao/{ident}/apagar-branch", json={})
    assert resposta.status_code == 200 and resposta.json()["branch_apagado_em"]
    assert cliente.get("/api/workspace/sessao/anteriores").json() == []
