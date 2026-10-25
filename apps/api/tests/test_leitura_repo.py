"""Leitura do checkout para o supervisor e o modelo local: buscar, listar, ler."""
import json
import subprocess
from unittest.mock import MagicMock

import pytest

from app.routers import ai
from app.services import autoridade, bancada_runner, leitura_repo


@pytest.fixture
def repo(tmp_path, monkeypatch):
    raiz = tmp_path / "repo"
    (raiz / "app").mkdir(parents=True)
    (raiz / "web").mkdir()
    (raiz / "tmp").mkdir()
    (raiz / "node_modules" / "pkg").mkdir(parents=True)
    (raiz / "app" / "mod.py").write_text("def current():\n    return 'x'\n", encoding="utf-8")
    (raiz / "web" / "Tela.tsx").write_text("export function current() {}\n", encoding="utf-8")
    (raiz / "tmp" / "copia.py").write_text("def current(): pass\n", encoding="utf-8")
    (raiz / ".env").write_text("current=SEGREDO\n", encoding="utf-8")
    (raiz / ".gitignore").write_text("tmp/\nnode_modules/\n", encoding="utf-8")
    (raiz / "node_modules" / "pkg" / "i.js").write_text("current\n", encoding="utf-8")
    (raiz / "app" / "dados.bin").write_bytes(b"current\x00\x01")
    (tmp_path / "fora.py").write_text("current\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(raiz)], check=True)
    subprocess.run(["git", "-C", str(raiz), "add", "app/mod.py", ".gitignore"], check=True)
    monkeypatch.setattr(bancada_runner, "REPO_TRABALHO", raiz)
    return raiz


def test_buscar_texto_acha_rastreado_e_novo_e_pula_ignorado_binario_e_env(repo):
    r = leitura_repo.buscar_texto("current")
    caminhos = {o["caminho"] for o in r["ocorrencias"]}
    # web/Tela.tsx não está no índice: arquivo novo também conta.
    assert caminhos == {"app/mod.py", "web/Tela.tsx"}
    assert {"caminho": "app/mod.py", "linha": 1, "texto": "def current():"} in r["ocorrencias"]


def test_buscar_texto_e_literal_e_restringe_pasta(repo):
    assert leitura_repo.buscar_texto("current(", "app")["ocorrencias"][0]["caminho"] == "app/mod.py"
    assert leitura_repo.buscar_texto("c.rrent")["ocorrencias"] == []


def test_buscar_texto_limita_ocorrencias(repo, monkeypatch):
    monkeypatch.setattr(leitura_repo, "MAX_OCORRENCIAS", 1)
    r = leitura_repo.buscar_texto("current")
    assert len(r["ocorrencias"]) == 1 and r["truncado"] is True


@pytest.mark.parametrize("caminho", ["../", "/etc", ".git", ".env"])
def test_recusa_fora_do_repo_e_bloqueados(repo, caminho):
    with pytest.raises(leitura_repo.Recusado):
        leitura_repo.buscar_texto("current", caminho)


def test_listar_pasta_esconde_bloqueados_e_gerados(repo):
    r = leitura_repo.listar_pasta(".")
    assert "app/" in r["itens"] and "web/" in r["itens"]
    assert not any(i.startswith((".env", ".git", "node_modules")) for i in r["itens"])
    assert leitura_repo.listar_pasta("app")["itens"] == ["app/dados.bin", "app/mod.py"]


def test_ler_arquivo_limita_linhas_e_recusa_binario(repo, monkeypatch):
    monkeypatch.setattr(leitura_repo, "MAX_LINHAS_ARQUIVO", 1)
    r = leitura_repo.ler_arquivo("app/mod.py", 1, 2)
    assert r == {"caminho": "app/mod.py", "inicio": 1, "fim": 1, "total_linhas": 2,
                 "texto": "def current():", "truncado": True}
    with pytest.raises(leitura_repo.Recusado, match="binário"):
        leitura_repo.ler_arquivo("app/dados.bin", 1, 1)


# ---------------------------------------------------------------- tools do supervisor

def _tool(nome, args):
    return json.loads(ai.executar_tool(nome, args, MagicMock(), nivel=autoridade.OBSERVE))


def test_supervisor_busca_e_lista_no_nivel_observar(repo):
    assert _tool("buscar_texto", {"texto": "current", "caminho": "app"})["ocorrencias"][0]["linha"] == 1
    assert "app/mod.py" in _tool("listar_pasta", {"caminho": "app"})["itens"]


def test_supervisor_recebe_erro_e_nao_excecao(repo):
    r = _tool("buscar_texto", {"texto": "current", "caminho": "../"})
    assert r["code"] == "leitura_recusada" and "fora do repositório" in r["erro"]
    assert _tool("listar_pasta", {"caminho": ".env"})["code"] == "leitura_recusada"
