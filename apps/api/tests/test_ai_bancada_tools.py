"""Tools de leitura do planejamento da Bancada no AI Hub: ler_task e ler_trecho."""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.backlog import BacklogItem
from app.models.project import Project
from app.models.subtask import BacklogSubtask
from app.routers import ai
from app.services import autoridade, bancada_runner


def _executar(nome, args, db=None):
    return json.loads(ai.executar_tool(nome, args, db or MagicMock(),
                                       nivel=autoridade.OBSERVE))


# ---------------------------------------------------------------- ler_trecho

@pytest.fixture
def repo(tmp_path, monkeypatch):
    raiz = tmp_path / "repo"
    (raiz / "app").mkdir(parents=True)
    (raiz / "app" / "mod.py").write_text(
        "\n".join(f"linha {i}" for i in range(1, 501)) + "\n", encoding="utf-8")
    (raiz / ".env").write_text("SEGREDO=x\n", encoding="utf-8")
    (raiz / ".git").mkdir()
    (raiz / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (tmp_path / "fora.txt").write_text("fora\n", encoding="utf-8")
    monkeypatch.setattr(bancada_runner, "REPO_TRABALHO", raiz)
    return raiz


def test_ler_trecho_devolve_linhas_reais(repo):
    r = _executar("ler_trecho", {"caminho": "app/mod.py", "inicio": 10, "fim": 12})
    assert r == {"caminho": "app/mod.py", "inicio": 10, "fim": 12,
                 "texto": "linha 10\nlinha 11\nlinha 12"}


def test_ler_trecho_limita_linhas_por_chamada(repo):
    r = _executar("ler_trecho", {"caminho": "app/mod.py", "inicio": 1, "fim": 500})
    assert r["fim"] == ai.LER_TRECHO_MAX_LINHAS
    assert r["truncado"] is True
    assert r["texto"].count("\n") == ai.LER_TRECHO_MAX_LINHAS - 1


@pytest.mark.parametrize("caminho", ["../fora.txt", "/etc/passwd"])
def test_ler_trecho_recusa_fora_do_repo(repo, caminho):
    r = _executar("ler_trecho", {"caminho": caminho, "inicio": 1, "fim": 1})
    assert "fora do repositório" in r["erro"]


def test_ler_trecho_recusa_symlink_para_fora(repo):
    (repo / "atalho.txt").symlink_to(repo.parent / "fora.txt")
    r = _executar("ler_trecho", {"caminho": "atalho.txt", "inicio": 1, "fim": 1})
    assert "fora do repositório" in r["erro"]


@pytest.mark.parametrize("caminho", [".env", ".git/config", "app/../.env"])
def test_ler_trecho_recusa_caminho_sensivel(repo, caminho):
    r = _executar("ler_trecho", {"caminho": caminho, "inicio": 1, "fim": 1})
    assert r["code"] == "trecho_bloqueado"
    assert "SEGREDO" not in json.dumps(r)


def test_ler_trecho_recusa_symlink_para_env(repo):
    (repo / "app" / "inocente.txt").symlink_to(repo / ".env")
    r = _executar("ler_trecho", {"caminho": "app/inocente.txt", "inicio": 1, "fim": 1})
    assert r["code"] == "trecho_bloqueado"


@pytest.mark.parametrize("inicio,fim", [(0, 3), (5, 2), ("a", 3), (None, 3), (-1, 1)])
def test_ler_trecho_recusa_intervalo_invalido(repo, inicio, fim):
    r = _executar("ler_trecho", {"caminho": "app/mod.py", "inicio": inicio, "fim": fim})
    assert r["code"] == "trecho_invalido"


def test_ler_trecho_recusa_intervalo_alem_do_fim_do_arquivo(repo):
    r = _executar("ler_trecho", {"caminho": "app/mod.py", "inicio": 900, "fim": 910})
    assert r["code"] == "trecho_invalido"


def test_ler_trecho_recusa_arquivo_inexistente(repo):
    r = _executar("ler_trecho", {"caminho": "app/nao_existe.py", "inicio": 1, "fim": 1})
    assert r["code"] == "trecho_invalido"


def test_ler_trecho_recusa_arquivo_grande_sem_ler(repo, monkeypatch):
    grande = repo / "app" / "grande.bin"
    with grande.open("wb") as f:
        f.truncate(ai.LER_TRECHO_MAX_BYTES + 1)
    lido = MagicMock()
    monkeypatch.setattr(bancada_runner, "ler_trecho", lido)
    r = _executar("ler_trecho", {"caminho": "app/grande.bin", "inicio": 1, "fim": 1})
    assert r["code"] == "trecho_grande"
    lido.assert_not_called()


def test_ler_trecho_recusa_binario(repo):
    (repo / "app" / "x.bin").write_bytes(b"abc\x00def\n")
    r = _executar("ler_trecho", {"caminho": "app/x.bin", "inicio": 1, "fim": 1})
    assert r["code"] == "trecho_binario"


def test_ler_trecho_limita_caracteres(repo):
    (repo / "app" / "min.js").write_text("x" * (ai.LER_TRECHO_MAX_CHARS + 50),
                                         encoding="utf-8")
    r = _executar("ler_trecho", {"caminho": "app/min.js", "inicio": 1, "fim": 1})
    assert len(r["texto"]) == ai.LER_TRECHO_MAX_CHARS
    assert r["truncado"] is True


# ---------------------------------------------------------------- ler_task

def _db_com(task=None, projeto=None, subtasks=()):
    """db falso: query(Model).filter(...)[.order_by(...)].first()/all()."""
    def query(modelo):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        if modelo is BacklogItem:
            q.first.return_value = task
        elif modelo is Project:
            q.first.return_value = projeto
        elif modelo is BacklogSubtask:
            q.all.return_value = list(subtasks)
        return q
    db = MagicMock()
    db.query.side_effect = query
    db.add.side_effect = AssertionError("ler_task não pode escrever")
    db.commit.side_effect = AssertionError("ler_task não pode escrever")
    return db


def _task(descricao):
    return SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(),
                           title="Ajustar X", description=descricao,
                           status="todo", priority="high", type="feature")


def test_ler_task_devolve_ficha_completa():
    t = _task("Fazer Y no arquivo Z")
    sub = SimpleNamespace(execution_order=1, title="passo 1", status="todo",
                          description=None)
    db = _db_com(t, SimpleNamespace(name="WorkDev Core", slug="workdev-core"), [sub])
    r = _executar("ler_task", {"task_id": str(t.id)}, db)
    assert r["titulo"] == "Ajustar X"
    assert r["descricao"] == "Fazer Y no arquivo Z"
    assert r["descricao_vazia"] is False
    assert "aviso" not in r
    assert r["projeto"] == {"nome": "WorkDev Core", "slug": "workdev-core"}
    assert r["status"] == "todo"
    assert r["subtasks"] == [{"ordem": 1, "titulo": "passo 1",
                              "status": "todo", "descricao": None}]


@pytest.mark.parametrize("descricao", [None, "", "   \n "])
def test_ler_task_descricao_vazia_e_explicita(descricao):
    t = _task(descricao)
    db = _db_com(t, SimpleNamespace(name="P", slug="p"))
    r = _executar("ler_task", {"task_id": str(t.id)}, db)
    assert r["descricao"] is None
    assert r["descricao_vazia"] is True
    assert "peça a descrição" in r["aviso"]


def test_ler_task_inexistente():
    r = _executar("ler_task", {"task_id": str(uuid.uuid4())}, _db_com(None))
    assert r == {"erro": "task não encontrada"}


@pytest.mark.parametrize("task_id", ["", "abc", None])
def test_ler_task_id_invalido_nao_consulta(task_id):
    db = _db_com(None)
    r = _executar("ler_task", {"task_id": task_id}, db)
    assert "inválido" in r["erro"]
    db.query.assert_not_called()


# ---------------------------------------------------------------- catálogo

def test_tools_novas_sao_leitura_e_aparecem_em_observe():
    nomes = {t["name"] for t in autoridade.tools_para(autoridade.OBSERVE, ai.TOOLS)}
    assert {"ler_task", "ler_trecho"} <= nomes
    assert autoridade.NIVEL_POR_TOOL["ler_task"] == autoridade.OBSERVE
    assert autoridade.NIVEL_POR_TOOL["ler_trecho"] == autoridade.OBSERVE
