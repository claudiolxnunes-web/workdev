"""Referências canônicas no Workspace: bloco no prompt do supervisor e tool ler_referencias."""
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import JSON, MetaData, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import DefaultClause

from app.models.adr import ADR
from app.models.backlog import BacklogItem
from app.models.chat import ChatMessage, ChatSession
from app.models.decision import Decision
from app.models.handoff import ExecutionPlan
from app.models.knowledge import KnowledgeEntry
from app.models.project import Project
from app.models.subtask import BacklogSubtask
from app.routers import ai, chat_sessions
from app.schemas.chat import WorkspacePlanningRequest
from app.services import autoridade

SEGREDO = "sk-ant-abcdefghijklmnopqrstuvwxyz0123"


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/ref.db")
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
        outro = Project(id=uuid4(), name="Outro", slug="outro", type="web", status="active")
        sessao.add_all([projeto, outro])
        sessao.commit()
        task = BacklogItem(id=uuid4(), project_id=projeto.id, title="Conexão do banco",
                           description="Trocar a DATABASE_URL do bridge docker", status="todo")
        sessao.add(task)
        sessao.add_all([
            ADR(id=uuid4(), project_id=projeto.id, title="Postgres pelo loopback", status="accepted",
                context="O bridge docker muda depois de reboot", decision=f"DATABASE_URL usa 127.0.0.1 {SEGREDO}",
                consequences="Não depende da rede do docker"),
            Decision(id=uuid4(), project_id=projeto.id, title="Deploy só com prova",
                     description="deploy.sh exige proof_id"),
            ADR(id=uuid4(), project_id=outro.id, title="ADR de outro projeto", status="accepted",
                context="bridge docker", decision="nada", consequences=""),
        ])
        sessao.commit()
        sessao.task, sessao.projeto = task, projeto
        yield sessao


def test_prompt_do_supervisor_leva_o_bloco_canonico_redigido(db):
    saida = chat_sessions.criar_sessao_planejamento_workspace(WorkspacePlanningRequest(task_id=db.task.id), db)
    prompt = db.query(ChatMessage).filter(ChatMessage.session_id == UUID(saida["id"])).one().content
    assert "## Contexto recuperado (somente leitura)" in prompt
    assert "[ADR] Postgres pelo loopback" in prompt and "127.0.0.1" in prompt
    assert SEGREDO not in prompt
    assert "ADR de outro projeto" not in prompt
    assert "validar_plano_workspace" in prompt and "ler_referencias" in prompt


def test_ler_referencias_filtra_projeto_tipo_e_termo_e_redige(db):
    def chamar(**args):
        return json.loads(ai.executar_tool("ler_referencias", args, db, autoridade.OBSERVE))
    tudo = chamar(task_id=str(db.task.id))
    assert tudo["projeto"] == "workdev-core" and {r["titulo"] for r in tudo["referencias"]} == {
        "Postgres pelo loopback", "Deploy só com prova"}
    adr = chamar(projeto_slug="workdev-core", tipo="adr")["referencias"][0]
    assert adr["status"] == "accepted" and "Consequencias: Não depende" in adr["texto"]
    assert SEGREDO not in adr["texto"]
    assert [r["titulo"] for r in chamar(projeto_slug="workdev-core", termo="PROOF_ID")["referencias"]] == [
        "Deploy só com prova"]
    assert chamar()["code"] == "sem_projeto"
    assert chamar(projeto_slug="nao-existe")["code"] == "nao_encontrado"


def test_tools_novas_sao_leitura():
    for nome in ("validar_plano_workspace", "ler_resultado_fatia", "ler_referencias"):
        assert autoridade.NIVEL_POR_TOOL[nome] == autoridade.OBSERVE
