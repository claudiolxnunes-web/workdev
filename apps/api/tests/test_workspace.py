"""Workspace: só leitura, lista do git, bloqueios, limites e máscara de chaves."""
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import workspace as rota
from app.services import workspace

CHAVE_FALSA = "-".join(["sk", "or", "v1", "abcdefghijklmnop"])


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "apps" / "api").mkdir(parents=True)
    (repo / "tmp" / "bancada").mkdir(parents=True)
    (repo / ".gitignore").write_text(".env\nignorado.txt\n")
    (repo / "apps" / "api" / "modulo.py").write_text("def current():\n    return 1\n")
    (repo / "apps" / "api" / "outro.py").write_text("X = 1\n")
    (repo / "README.md").write_text("# repo\n")
    (repo / "config.py").write_text(f"CHAVE = '{CHAVE_FALSA}'\n")
    (repo / "imagem.bin").write_bytes(b"\x89PNG\0\0\0dados")
    (repo / "tmp" / "bancada" / "parecer.json").write_text("{}")
    (repo / ".workdev-recovery").mkdir()
    (repo / ".workdev-recovery" / "tracked.patch").write_text("+SEGREDO=1\n")
    git(repo, "init", "-q")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    (repo / ".env").write_text("SEGREDO=1\n")
    (repo / "ignorado.txt").write_text("nao aparece\n")
    (repo / "apps" / "api" / "modulo.py").write_text("def current():\n    return 2\n")
    (repo / "apps" / "api" / "novo.py").write_text("Y = 1\nZ = 2\n")
    (tmp_path / "fora.txt").write_text("CONTEUDO_EXTERNO\n")
    (repo / "atalho.txt").symlink_to(tmp_path / "fora.txt")
    monkeypatch.setattr(workspace, "REPO", repo)
    app = FastAPI()
    app.include_router(rota.router, prefix="/api")
    return TestClient(app)


def nomes(resposta):
    return [item["nome"] for item in resposta.json()["itens"]]


def test_arvore_vem_do_git_e_esconde_ignorados_e_bloqueados(cliente):
    raiz = cliente.get("/api/workspace/arvore")
    assert raiz.status_code == 200
    assert nomes(raiz) == ["apps", "README.md", "atalho.txt", "config.py", "imagem.bin"]
    assert nomes(cliente.get("/api/workspace/arvore", params={"pasta": "apps/api"})) == ["modulo.py", "novo.py", "outro.py"]
    texto = raiz.text + cliente.get("/api/workspace/arvore", params={"pasta": "apps/api"}).text
    for proibido in (".env", "ignorado", "tmp", ".gitignore", ".workdev-recovery"):
        assert proibido not in texto


@pytest.mark.parametrize("pasta,status", [("../", 422), ("tmp", 403), ("tmp/bancada", 403), ("nao_existe", 404)])
def test_arvore_recusa_pastas_fora_ou_bloqueadas(cliente, pasta, status):
    assert cliente.get("/api/workspace/arvore", params={"pasta": pasta}).status_code == status


def test_arquivo_le_texto_e_mascara_chaves(cliente):
    corpo = cliente.get("/api/workspace/arquivo", params={"caminho": "apps/api/modulo.py"}).json()
    assert corpo["texto"] == "def current():\n    return 2\n" and corpo["linhas"] == 2
    config = cliente.get("/api/workspace/arquivo", params={"caminho": "config.py"})
    assert CHAVE_FALSA not in config.text and "[mascarado]" in config.json()["texto"]


@pytest.mark.parametrize("caminho,status", [
    (".env", 403), ("ignorado.txt", 404), ("../fora.txt", 422), ("atalho.txt", 422),
    ("tmp/bancada/parecer.json", 403), (".workdev-recovery/tracked.patch", 403), ("/etc/passwd", 404), (".git/config", 403),
])
def test_arquivo_recusa_o_que_nao_pode_aparecer(cliente, caminho, status):
    resposta = cliente.get("/api/workspace/arquivo", params={"caminho": caminho})
    assert resposta.status_code == status
    assert "SEGREDO" not in resposta.text and "CONTEUDO_EXTERNO" not in resposta.text


def test_binario_nao_e_exibido_e_arquivo_grande_e_truncado(cliente, monkeypatch):
    binario = cliente.get("/api/workspace/arquivo", params={"caminho": "imagem.bin"}).json()
    assert binario["binario"] is True and binario["texto"] == ""
    monkeypatch.setattr(workspace, "LIMITE_ARQUIVO", 10)
    grande = cliente.get("/api/workspace/arquivo", params={"caminho": "apps/api/modulo.py"}).json()
    assert grande["truncado"] is True and len(grande["texto"]) == 10


def test_alteracoes_e_diff_por_arquivo(cliente):
    corpo = cliente.get("/api/workspace/alteracoes").json()
    itens = {i["caminho"]: i for i in corpo["itens"]}
    assert set(itens) == {"apps/api/modulo.py", "apps/api/novo.py", "atalho.txt"}
    assert itens["apps/api/modulo.py"] == {"caminho": "apps/api/modulo.py", "estado": "M", "mais": 1, "menos": 1}
    assert itens["apps/api/novo.py"]["estado"] == "novo" and itens["apps/api/novo.py"]["mais"] == 2
    diff = cliente.get("/api/workspace/diff", params={"caminho": "apps/api/modulo.py"}).json()["diff"]
    assert "-    return 1" in diff and "+    return 2" in diff
    novo = cliente.get("/api/workspace/diff", params={"caminho": "apps/api/novo.py"}).json()["diff"]
    assert "+Y = 1" in novo
    assert cliente.get("/api/workspace/diff", params={"caminho": "README.md"}).status_code == 404
    assert cliente.get("/api/workspace/diff", params={"caminho": ".env"}).status_code == 403


def test_arquivo_novo_grande_nao_e_lido_para_contar_linhas(cliente, monkeypatch):
    monkeypatch.setattr(workspace, "LIMITE_ARQUIVO", 5)
    itens = {i["caminho"]: i for i in cliente.get("/api/workspace/alteracoes").json()["itens"]}
    assert itens["apps/api/novo.py"]["estado"] == "novo" and itens["apps/api/novo.py"]["mais"] is None


def test_git_lento_ou_quebrado_vira_erro_claro(cliente, monkeypatch):
    def lento(*a, **k):
        raise subprocess.TimeoutExpired("git", 10)
    monkeypatch.setattr(workspace.subprocess, "run", lento)
    resposta = cliente.get("/api/workspace/alteracoes")
    assert resposta.status_code == 504 and resposta.json()["detail"]["code"] == "git_lento"


def test_rotas_sao_somente_get(cliente):
    for caminho in ("/api/workspace/arvore", "/api/workspace/arquivo", "/api/workspace/alteracoes", "/api/workspace/diff"):
        assert cliente.post(caminho).status_code == 405


def test_exige_login_no_app_real():
    from app.main import app
    with TestClient(app) as cliente:
        assert cliente.get("/api/workspace/arvore").status_code == 401
