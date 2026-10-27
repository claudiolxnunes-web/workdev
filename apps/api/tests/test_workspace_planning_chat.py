"""Supervisor do Workspace Local: sessão própria, sem colidir com a do AI Hub.

O Workspace tem outro destino que a Bancada: aqui o modelo local lê o repositório
sozinho, então o supervisor orienta em vez de micro-tarefar. A sessão criada
para o Workspace não pode tomar a vaga da task reservada ao AI Hub
(uq_chat_sessions_task_id).
"""
from uuid import uuid4

import pytest
from sqlalchemy import JSON, MetaData, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import DefaultClause

from app.models.adr import ADR
from app.models.backlog import BacklogItem
from app.models.decision import Decision
from app.models.knowledge import KnowledgeEntry
from app.models.chat import ChatMessage, ChatSession
from app.models.handoff import ExecutionPlan
from app.models.project import Project
from app.models.subtask import BacklogSubtask
from app.routers import chat_sessions
from app.schemas.chat import BancadaPlanningRequest, SessionFromTask, WorkspacePlanningRequest
from app.services import autoridade


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/chat.db")
    metadata = MetaData()
    for model in (Project, BacklogItem, BacklogSubtask, ChatSession, ChatMessage, ExecutionPlan,
                  ADR, Decision, KnowledgeEntry):
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


def test_workspace_nao_colide_com_a_sessao_do_ai_hub(db):
    plan = chat_sessions.criar_sessao_da_task(SessionFromTask(task_id=db.task.id), db)

    workspace = chat_sessions.criar_sessao_planejamento_workspace(
        WorkspacePlanningRequest(task_id=db.task.id), db)

    assert workspace["id"] != plan["id"]
    assert workspace["task_id"] == str(db.task.id)
    sessao = db.query(ChatSession).filter(ChatSession.title.like("Supervisar Workspace:%")).one()
    assert sessao.task_id is None and sessao.authority == autoridade.OBSERVE
    prompt = db.query(ChatMessage).filter(ChatMessage.session_id == sessao.id).one().content
    assert f"Task ID: `{db.task.id}`" in prompt
    # O prompt do supervisor é o do Workspace: orientação em fatias com gate,
    # não o micro-tarefas da Bancada.
    assert "supervisor do Workspace Local" in prompt
    assert "fatias" in prompt
    assert "NÃO edita arquivos" in prompt
    assert "validar_lote_bancada" not in prompt


def test_workspace_e_bancada_tem_sessoes_separadas(db):
    bancada = chat_sessions.criar_sessao_planejamento_bancada(
        BancadaPlanningRequest(task_id=db.task.id), db)
    workspace = chat_sessions.criar_sessao_planejamento_workspace(
        WorkspacePlanningRequest(task_id=db.task.id), db)

    assert bancada["id"] != workspace["id"]
    prompts = {
        sessao.title.split(":")[0]: sessao
        for sessao in db.query(ChatSession).all()
    }
    assert set(prompts) == {"Planejar Bancada", "Supervisar Workspace"}
    conteudos = {
        titulo: db.query(ChatMessage).filter(ChatMessage.session_id == sessao.id).one().content
        for titulo, sessao in prompts.items()
    }
    assert "validar_lote_bancada" in conteudos["Planejar Bancada"]
    assert "validar_lote_bancada" not in conteudos["Supervisar Workspace"]


def test_task_sem_descricao_recusa_o_workspace(db):
    db.task.description = "   "
    db.commit()
    with pytest.raises(Exception) as erro:
        chat_sessions.criar_sessao_planejamento_workspace(
            WorkspacePlanningRequest(task_id=db.task.id), db)
    assert "descrição" in str(erro.value).lower()
