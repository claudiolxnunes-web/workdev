"""Fatias de banco: validação do SQL, simulação sem gravar, aplicar com trava, reverter com trava."""
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import JSON, MetaData, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import DefaultClause

from app.models.backlog import BacklogItem
from app.models.project import Project
from app.services import workspace_banco as banco
from app.services.workspace import WorkspaceErro

VERIF = ["SELECT count(*) = 2 FROM backlog WHERE priority = 'high'"]


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path}/b.db")
    metadata = MetaData()
    for model in (Project, BacklogItem):
        tabela = model.__table__.to_metadata(metadata)
        for coluna in tabela.columns:
            if isinstance(coluna.type, JSONB):
                coluna.type = JSON()
            if coluna.server_default is not None:
                valor = str(coluna.server_default.arg).replace("gen_random_uuid()", "(lower(hex(randomblob(16))))")
                coluna.server_default = DefaultClause(text(valor.replace("now()", "CURRENT_TIMESTAMP").replace("::jsonb", "")))
    metadata.create_all(engine)
    monkeypatch.setattr(banco, "_engine", lambda: engine)
    with sessionmaker(bind=engine)() as sessao:
        projeto = Project(id=uuid4(), name="P", slug="p", type="web", status="active")
        sessao.add(projeto)
        sessao.flush()
        for titulo, prioridade in (("a", "low"), ("b", "low"), ("c", "medium")):
            sessao.add(BacklogItem(id=uuid4(), project_id=projeto.id, title=titulo, description="d",
                                   status="todo", priority=prioridade))
        sessao.commit()
    return engine


def prioridades(engine) -> dict:
    with engine.connect() as c:
        return {t: p for t, p in c.execute(text("SELECT title, priority FROM backlog"))}


UPDATE = "UPDATE backlog SET priority = 'high' WHERE priority = 'low'"


# ---------------------------------------------------------------- validação

def test_aceita_dml_nas_tabelas_de_registro():
    assert banco.validar_sql(UPDATE + ";")["comando"] == "UPDATE"
    assert banco.validar_sql("DELETE FROM public.adrs WHERE id = 'x'")["tabela"] == "adrs"
    assert banco.validar_sql("INSERT INTO knowledge (title) VALUES ('drop table; -- não é comando')")["comando"] == "INSERT"


@pytest.mark.parametrize("sql,codigo", [
    ("ALTER TABLE backlog ADD COLUMN x int", "sql_nao_permitido"),
    ("DROP TABLE backlog", "sql_nao_permitido"),
    ("UPDATE backlog SET priority = 'x'", "sem_where"),
    ("DELETE FROM backlog", "sem_where"),
    ("UPDATE ai_budgets SET limite = 0 WHERE true", "tabela_nao_permitida"),
    ("UPDATE backlog SET title = 'x' WHERE true; DELETE FROM adrs WHERE true", "sql_multiplo"),
    ("UPDATE backlog SET title = 'x' WHERE true -- some", "sql_com_comentario"),
    ("UPDATE backlog SET title = pg_read_file('/etc/passwd') WHERE true", "funcao_proibida"),
    ("UPDATE backlog SET title = 'x' WHERE true RETURNING *", "sql_nao_permitido"),
    ("SELECT * FROM backlog", "sql_nao_permitido"),
    ("", "sql_vazio"),
])
def test_recusa(sql, codigo):
    with pytest.raises(WorkspaceErro) as erro:
        banco.validar_sql(sql)
    assert erro.value.codigo == codigo


def test_tabelas_liberadas_por_fatia_restringem_mais():
    with pytest.raises(WorkspaceErro):
        banco.validar_sql(UPDATE, ["adrs"])


def test_verificacao_so_le():
    assert banco.validar_verificacao(VERIF[0] + ";").startswith("SELECT")
    for ruim in ("DELETE FROM backlog WHERE true", "SELECT 1; DELETE FROM backlog WHERE true",
                 "SELECT pg_sleep(10)", "WITH x AS (DELETE FROM backlog RETURNING *) SELECT 1"):
        with pytest.raises(WorkspaceErro):
            banco.validar_verificacao(ruim)


# ---------------------------------------------------------------- simular / aplicar

def test_simular_mostra_antes_e_depois_e_nao_grava(db):
    s = banco.simular(UPDATE, VERIF)
    assert s["linhas"] == 2 and s["passou"] is True
    assert {r["priority"] for r in s["antes"]} == {"low"} and {r["priority"] for r in s["depois"]} == {"high"}
    assert s["verificacoes"][0]["passou"] is True
    assert prioridades(db) == {"a": "low", "b": "low", "c": "medium"}


def test_simular_reprova_verificacao_falsa_e_linhas_demais(db, monkeypatch):
    assert banco.simular(UPDATE, ["SELECT count(*) = 99 FROM backlog"])["passou"] is False
    monkeypatch.setattr(banco, "MAX_LINHAS", 1)
    assert banco.simular(UPDATE, VERIF)["passou"] is False
    with pytest.raises(WorkspaceErro) as erro:
        banco.simular("UPDATE backlog SET nao_existe = 1 WHERE true", VERIF)
    assert erro.value.codigo == "sql_falhou"
    with pytest.raises(WorkspaceErro) as erro:
        banco.simular(UPDATE, [])
    assert erro.value.codigo == "sem_verificacao"


def test_aplicar_grava_e_reverter_restaura(db):
    s = banco.simular(UPDATE, VERIF)
    aplicado = banco.aplicar(s, VERIF)
    assert prioridades(db) == {"a": "high", "b": "high", "c": "medium"} and aplicado["linhas"] == 2
    banco.reverter(aplicado)
    assert prioridades(db) == {"a": "low", "b": "low", "c": "medium"}


def test_aplicar_recusa_se_as_linhas_mudaram_desde_a_simulacao(db):
    s = banco.simular(UPDATE, ["SELECT 1"])
    with db.begin() as c:
        c.execute(text("UPDATE backlog SET priority = 'low' WHERE title = 'c'"))
    with pytest.raises(WorkspaceErro) as erro:
        banco.aplicar(s, ["SELECT 1"])
    assert erro.value.codigo == "linhas_mudaram"
    assert prioridades(db) == {"a": "low", "b": "low", "c": "low"}


def test_aplicar_recusa_simulacao_reprovada_vencida_ou_trocada(db, monkeypatch):
    with pytest.raises(WorkspaceErro) as erro:
        banco.aplicar(banco.simular(UPDATE, ["SELECT 0"]), ["SELECT 0"])
    assert erro.value.codigo == "simulacao_reprovada"
    s = banco.simular(UPDATE, VERIF)
    with pytest.raises(WorkspaceErro) as erro:
        banco.aplicar(s, ["SELECT 1"])
    assert erro.value.codigo == "simulacao_diferente"
    s["simulado_em"] -= banco.VALIDADE_SIMULACAO_S + 1
    with pytest.raises(WorkspaceErro) as erro:
        banco.aplicar(s, VERIF)
    assert erro.value.codigo == "simulacao_vencida"


def test_reverter_recusa_linha_que_mudou_depois_salvo_forcado(db):
    aplicado = banco.aplicar(banco.simular(UPDATE, VERIF), VERIF)
    with db.begin() as c:
        c.execute(text("UPDATE backlog SET priority = 'urgent' WHERE title = 'a'"))
    with pytest.raises(WorkspaceErro) as erro:
        banco.reverter(aplicado)
    assert erro.value.codigo == "linha_mudou"
    assert prioridades(db)["a"] == "urgent"
    banco.reverter(aplicado, forcar=True)
    assert prioridades(db) == {"a": "low", "b": "low", "c": "medium"}


def test_delete_e_insert_revertem(db):
    verif = ["SELECT count(*) = 1 FROM backlog"]
    apagado = banco.aplicar(banco.simular("DELETE FROM backlog WHERE priority = 'low'", verif), verif)
    assert set(prioridades(db)) == {"c"} and {r["title"] for r in apagado["antes"]} == {"a", "b"}
    banco.reverter(apagado)
    assert set(prioridades(db)) == {"a", "b", "c"}
    with db.connect() as c:
        projeto = c.execute(text("SELECT id FROM projects")).scalar()
    novo = f"INSERT INTO backlog (id, project_id, title, status, priority) VALUES ('{uuid4().hex}', '{projeto}', 'novo', 'todo', 'low')"
    verif = ["SELECT count(*) = 4 FROM backlog"]
    inserido = banco.aplicar(banco.simular(novo, verif), verif)
    assert "novo" in prioridades(db)
    banco.reverter(inserido)
    assert "novo" not in prioridades(db)


def test_ler_schema_so_estrutura(db):
    schema = banco.ler_schema("backlog")
    assert "priority" in [c["nome"] for c in schema["colunas"]] and "linhas" not in schema
    with pytest.raises(WorkspaceErro):
        banco.ler_schema("ai_budgets")


def test_trilha_grava_json(tmp_path):
    arquivo = banco.trilha(tmp_path, "s1", 2, "aplicado", {"quando": datetime(2026, 1, 1)})
    assert arquivo.name.startswith("fatia02-aplicado-") and "2026-01-01" in arquivo.read_text()
