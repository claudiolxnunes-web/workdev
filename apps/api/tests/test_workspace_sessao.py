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
