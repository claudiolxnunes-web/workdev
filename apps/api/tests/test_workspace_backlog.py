"""Workspace → backlog: fatias viram subtasks, status acompanham, fechar a task é do operador."""
from uuid import uuid4

import pytest
from sqlalchemy import JSON, MetaData, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import DefaultClause

from app.models.backlog import BacklogItem
from app.models.project import Project
from app.models.subtask import BacklogSubtask
from app.services import workspace_backlog as wb


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(wb, "_sincronizar_grafo", lambda sub, project_id: None)
    engine = create_engine(f"sqlite:///{tmp_path}/b.db")
    metadata = MetaData()
    for model in (Project, BacklogItem, BacklogSubtask):
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
            if column.server_default is not None:
                valor = str(column.server_default.arg).replace("gen_random_uuid()", "(lower(hex(randomblob(16))))")
                column.server_default = DefaultClause(text(valor.replace("now()", "CURRENT_TIMESTAMP").replace("::jsonb", "")))
    metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as sessao:
        projeto = Project(id=uuid4(), name="P", slug="p", type="web", status="active")
        sessao.add(projeto)
        sessao.commit()
        sessao.task = BacklogItem(id=uuid4(), project_id=projeto.id, title="T", description="d", status="todo")
        sessao.add(sessao.task)
        sessao.commit()
        yield sessao


FATIAS = [{"n": 1, "objetivo": "um", "instrucao": "faça um", "gate": ["pytest"]},
          {"n": 2, "objetivo": "dois", "instrucao": "faça dois", "gate": ["build", "olhar a tela"]}]


def test_fatias_viram_subtasks_em_ordem(db):
    ids = wb.criar_subtasks(db, str(db.task.id), FATIAS)
    subs = db.query(BacklogSubtask).order_by(BacklogSubtask.execution_order).all()
    assert [str(s.id) for s in subs] == ids
    assert [s.title for s in subs] == ["Fatia 1: um", "Fatia 2: dois"]
    assert subs[1].description.endswith("Gate:\n- build\n- olhar a tela")
    assert {s.assigned_agent for s in subs} == {"workspace-local"}


def test_status_acompanham_e_a_task_nunca_fecha_sozinha(db):
    ids = wb.criar_subtasks(db, str(db.task.id), FATIAS)
    wb.task_em_andamento(db, str(db.task.id))
    wb.marcar_subtask(db, ids[0], "done", "Commit abc1234")
    wb.marcar_subtask(db, ids[1], "blocked", "Falhou em gate: x")
    db.refresh(db.task)
    assert db.task.status == "doing"
    subs = {str(s.id): s for s in db.query(BacklogSubtask).all()}
    assert (subs[ids[0]].status, subs[ids[0]].result) == ("done", "Commit abc1234")
    assert subs[ids[1]].status == "blocked"


def test_trocar_plano_remove_so_o_que_nao_comecou(db):
    ids = wb.criar_subtasks(db, str(db.task.id), FATIAS)
    wb.marcar_subtask(db, ids[0], "doing")
    assert wb.remover_subtasks_nao_iniciadas(db, ids) == 1
    assert [str(s.id) for s in db.query(BacklogSubtask).all()] == [ids[0]]


def test_task_inexistente_ou_fechada_nao_quebra(db):
    assert wb.criar_subtasks(db, str(uuid4()), FATIAS) == [None, None]
    db.task.status = "done"
    db.commit()
    wb.task_em_andamento(db, str(db.task.id))
    db.refresh(db.task)
    assert db.task.status == "done"
