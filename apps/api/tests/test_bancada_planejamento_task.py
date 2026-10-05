"""Planejar para a Bancada a partir de uma task: sem colidir com a sessão do AI Hub
(uq_chat_sessions_task_id) e com o planejador OpenRouter lendo a tabela certa."""
import importlib
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import JSON, MetaData, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import DefaultClause

from app.models.backlog import BacklogItem
from app.models.chat import ChatMessage, ChatSession
from app.models.handoff import ExecutionPlan
from app.models.project import Project
from app.models.subtask import BacklogSubtask
from app.routers import chat_sessions
from app.schemas.chat import BancadaPlanningRequest, SessionFromTask
from app.services import autoridade

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


# ---------------------------------------------------------------- sessão de chat

@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/chat.db")
    metadata = MetaData()
    for model in (Project, BacklogItem, BacklogSubtask, ChatSession, ChatMessage, ExecutionPlan):
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
            if column.server_default is not None:
                valor = str(column.server_default.arg)
                valor = valor.replace("gen_random_uuid()", "(lower(hex(randomblob(16))))")
                valor = valor.replace("now()", "CURRENT_TIMESTAMP").replace("::jsonb", "")
                column.server_default = DefaultClause(text(valor))
    metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as sessao:
        projeto = Project(id=uuid4(), name="WorkDev Core", slug="workdev-core", type="web", status="active")
        sessao.add(projeto)
        sessao.commit()
        task = BacklogItem(id=uuid4(), project_id=projeto.id, title="Knowledge",
                           description="Adicionar POST /api/knowledge", status="todo")
        sessao.add(task)
        sessao.commit()
        sessao.task = task
        yield sessao


def test_bancada_nao_colide_com_a_sessao_do_ai_hub(db):
    plan = chat_sessions.criar_sessao_da_task(SessionFromTask(task_id=db.task.id), db)

    bancada = chat_sessions.criar_sessao_planejamento_bancada(
        BancadaPlanningRequest(task_id=db.task.id), db)

    assert bancada["id"] != plan["id"]
    assert bancada["task_id"] == str(db.task.id)
    sessao = db.query(ChatSession).filter(ChatSession.title.like("Planejar Bancada:%")).one()
    assert sessao.task_id is None and sessao.authority == autoridade.OBSERVE
    prompt = db.query(ChatMessage).filter(ChatMessage.session_id == sessao.id).one().content
    assert f"Task ID: `{db.task.id}`" in prompt


def test_ai_hub_depois_da_bancada_continua_criando_sessao_de_plan(db):
    chat_sessions.criar_sessao_planejamento_bancada(BancadaPlanningRequest(task_id=db.task.id), db)

    plan = chat_sessions.criar_sessao_da_task(SessionFromTask(task_id=db.task.id), db)

    sessao = db.query(ChatSession).filter(ChatSession.task_id == db.task.id).one()
    assert str(sessao.id) == str(plan["id"]) and sessao.authority == autoridade.PLAN


# ---------------------------------------------------------------- planejador OpenRouter

class Cursor:
    def __init__(self, linhas):
        self.linhas, self.sql, self.params = linhas, None, None

    def execute(self, sql, params):
        self.sql, self.params = sql, params

    def fetchall(self):
        return self.linhas

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Conexao:
    def __init__(self, linhas):
        self.cur = Cursor(linhas)

    def cursor(self):
        return self.cur

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture
def planner(monkeypatch):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    modulo = importlib.import_module("bancada_planner")
    monkeypatch.setattr(modulo, "_ler_claude_md", lambda: "# WorkDev")
    return modulo


def _conexoes(monkeypatch, planner, *respostas):
    feitas = []

    def conectar():
        feitas.append(Conexao(respostas[len(feitas)]))
        return feitas[-1]

    monkeypatch.setattr(planner, "_conectar", conectar)
    return feitas


def test_task_e_lida_da_tabela_backlog(monkeypatch, planner):
    ident = uuid4()
    feitas = _conexoes(monkeypatch, planner, [(ident, "Knowledge", "Adicionar rota")], [(ident, "Knowledge", "x")])

    contexto, _ = planner._montar_contexto(str(ident)[:8], None)

    assert "Task: Knowledge\nAdicionar rota" in contexto
    assert f"- [{str(ident)[:8]}] Knowledge" in contexto
    assert "FROM backlog" in feitas[0].cur.sql and feitas[0].cur.params == (str(ident)[:8] + "%",)
    assert "FROM backlog" in feitas[1].cur.sql and feitas[1].cur.params[0] == ["todo", "doing", "blocked"]


@pytest.mark.parametrize("linhas, codigo", [
    ([], "tarefa_nao_encontrada"),
    ([(uuid4(), "a", "x"), (uuid4(), "b", "y")], "tarefa_ambigua"),
    ([(uuid4(), "a", "  ")], "descricao_vazia"),
])
def test_erros_da_task_sao_explicitos(monkeypatch, planner, linhas, codigo):
    _conexoes(monkeypatch, planner, linhas)
    with pytest.raises(planner.PlanejadorErro) as erro:
        planner._montar_contexto("1234abcd", None)
    assert erro.value.codigo == codigo


def test_id_invalido_nem_consulta_o_banco(monkeypatch, planner):
    feitas = _conexoes(monkeypatch, planner)
    with pytest.raises(planner.PlanejadorErro) as erro:
        planner._montar_contexto("abc", None)
    assert erro.value.codigo == "tarefa_invalida" and not feitas


def test_banco_fora_do_ar_nao_vira_task_nao_encontrada(monkeypatch, planner):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(planner.PlanejadorErro) as erro:
        planner._montar_contexto("1234abcd", None)
    assert erro.value.codigo == "banco_indisponivel"


def test_prompt_livre_segue_sem_banco(monkeypatch, planner):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    contexto, _ = planner._montar_contexto(None, "Documentar a função X")
    assert "Documentar a função X" in contexto
