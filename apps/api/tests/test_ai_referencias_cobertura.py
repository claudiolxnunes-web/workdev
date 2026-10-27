"""Cobertura de ADRs e decisões no AI Hub.

Duas faces do mesmo problema (achado Médio #3 da auditoria
`docs/AGENT_REFERENCE_CONTEXT_AUDIT.md`):

1. O contexto automático do AI Hub (`context_engine`) não coletava a tabela
   `decisions` — o planejador via os ADRs como índice e nenhuma decisão.
2. Não havia listagem dedicada de ADR nem de decisão: o modelo só tinha
   `ler_referencias`, que devolve o texto integral e filtra por termo.

O contrato testado aqui: o índice entra no contexto (título/status/data e
título/descrição recortada), o texto integral fica na tool de leitura, e as
listagens são do nível Observar — sem escalation e sem escrita.
"""

import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import JSON, MetaData, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import DefaultClause

from app.models.adr import ADR
from app.models.backlog import BacklogItem
from app.models.decision import Decision
from app.models.handoff import AgentRun, ExecutionPlan
from app.models.knowledge import KnowledgeEntry
from app.models.project import Project
from app.models.subtask import BacklogSubtask
from app.routers import ai
from app.services import autoridade as aut
from app.services import context_engine as ce

MODELOS = (Project, BacklogItem, BacklogSubtask, ADR, Decision, KnowledgeEntry,
           ExecutionPlan, AgentRun)

TEXTO_ADR = "O bridge docker muda de IP depois de reboot do host"


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/referencias.db")
    metadata = MetaData()
    for model in MODELOS:
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
        projeto = Project(id=uuid4(), name="WorkDev Core", slug="workdev-core",
                          type="web", status="active")
        outro = Project(id=uuid4(), name="Outro", slug="outro", type="web", status="active")
        sessao.add_all([projeto, outro])
        sessao.commit()
        sessao.add_all([
            ADR(id=uuid4(), project_id=projeto.id, title="Postgres pelo loopback",
                status="accepted", context=TEXTO_ADR,
                decision="DATABASE_URL aponta para 127.0.0.1",
                consequences="Não depende da rede do docker"),
            ADR(id=uuid4(), project_id=outro.id, title="ADR de outro projeto",
                status="proposed", context="contexto", decision="decisao", consequences=""),
            Decision(id=uuid4(), project_id=projeto.id, title="Deploy só com prova",
                     description="deploy.sh exige proof_id assinado"),
            Decision(id=uuid4(), project_id=outro.id, title="Decisão de outro projeto",
                     description="não é do WorkDev Core"),
        ])
        sessao.commit()
        sessao.projeto, sessao.outro = projeto, outro
        yield sessao


# --------------------------------------------------------------------------
# Contexto automático: decisões entram, texto integral não
# --------------------------------------------------------------------------


def test_coletar_decisoes_devolve_titulo_data_e_descricao(db):
    decisoes = ce.coletar_decisoes(db, db.projeto.id)

    assert [d["titulo"] for d in decisoes] == ["Deploy só com prova"]
    assert decisoes[0]["descricao"] == "deploy.sh exige proof_id assinado"
    assert decisoes[0]["data"] is not None


def test_coletar_decisoes_ignora_outro_projeto(db):
    decisoes = ce.coletar_decisoes(db, db.projeto.id)

    assert "Decisão de outro projeto" not in [d["titulo"] for d in decisoes]


def test_coletar_decisoes_respeita_o_limite_de_itens(db):
    for indice in range(7):
        db.add(Decision(id=uuid4(), project_id=db.projeto.id,
                        title=f"Decisão {indice}", description="texto"))
    db.commit()

    decisoes = ce.coletar_decisoes(db, db.projeto.id)

    assert len(decisoes) == ce.LIMITE_DECISOES


def test_coletar_decisoes_recorta_a_descricao(db):
    db.add(Decision(id=uuid4(), project_id=db.projeto.id, title="Decisão longa",
                    description="y" * 5000))
    db.commit()

    decisoes = {d["titulo"]: d for d in ce.coletar_decisoes(db, db.projeto.id)}
    descricao = decisoes["Decisão longa"]["descricao"]

    assert len(descricao) == ce.LIMITE_TEXTO_DECISAO
    assert descricao.endswith("…")


def test_contexto_de_projeto_inclui_decisoes(db):
    contexto = ce.montar_contexto_projeto(db, db.projeto)

    assert "decisoes" in contexto
    assert contexto["decisoes"][0]["titulo"] == "Deploy só com prova"


def test_contexto_renderizado_mostra_a_decisao(db):
    texto = ce.renderizar_contexto(ce.montar_contexto_projeto(db, db.projeto))

    assert "Decisões do projeto" in texto
    assert "Deploy só com prova" in texto
    assert "deploy.sh exige proof_id assinado" in texto


def test_texto_integral_da_adr_nao_entra_no_contexto(db):
    texto = ce.renderizar_contexto(ce.montar_contexto_projeto(db, db.projeto))

    assert "Postgres pelo loopback" in texto
    assert TEXTO_ADR not in texto
    assert "127.0.0.1" not in texto


def test_bloco_de_referencias_respeita_o_teto_de_caracteres():
    """O bloco renderizado respeita o teto declarado e diz que truncou."""
    bloco = ce._bloco_referencias({
        "adrs": [{"titulo": "a" * 300, "status": "proposed", "data": "2026-10-27"}
                 for _ in range(30)],
        "decisoes": [{"titulo": "d" * 300, "descricao": "x" * 200, "data": "2026-10-27"}
                     for _ in range(30)],
    })

    assert len("\n".join(bloco)) <= ce.LIMITE_BLOCO_REFERENCIAS
    assert "referências truncadas" in "\n".join(bloco)


def test_bloco_de_referencias_sem_excesso_nao_marca_truncamento():
    bloco = ce._bloco_referencias({
        "adrs": [{"titulo": "Postgres pelo loopback", "status": "accepted",
                  "data": "2026-10-27"}],
        "decisoes": [{"titulo": "Deploy só com prova", "descricao": "exige proof_id",
                      "data": "2026-10-27"}],
    })

    texto = "\n".join(bloco)
    assert "referências truncadas" not in texto
    assert "Postgres pelo loopback" in texto
    assert "Deploy só com prova" in texto


# --------------------------------------------------------------------------
# Tools de listagem (nível Observar)
# --------------------------------------------------------------------------


def test_listar_adrs_devolve_indice_sem_o_texto_da_adr(db):
    saida = json.loads(ai.executar_tool("listar_adrs", {"projeto_slug": "workdev-core"},
                                        db, aut.OBSERVE))

    assert saida["total"] == 1
    adr = saida["referencias"][0]
    assert adr["titulo"] == "Postgres pelo loopback"
    assert adr["status"] == "accepted"
    assert adr["data"] is not None
    assert TEXTO_ADR not in json.dumps(saida, ensure_ascii=False)
    assert "127.0.0.1" not in json.dumps(saida, ensure_ascii=False)


def test_listar_decisoes_devolve_indice_com_titulo_e_data(db):
    saida = json.loads(ai.executar_tool("listar_decisoes", {"projeto_slug": "workdev-core"},
                                        db, aut.OBSERVE))

    assert saida["total"] == 1
    decisao = saida["referencias"][0]
    assert decisao["titulo"] == "Deploy só com prova"
    assert decisao["data"] is not None
    assert "proof_id" not in json.dumps(saida, ensure_ascii=False)


def test_listagem_sem_slug_traz_os_dois_projetos(db):
    adrs = json.loads(ai.executar_tool("listar_adrs", {}, db, aut.OBSERVE))
    decisoes = json.loads(ai.executar_tool("listar_decisoes", {}, db, aut.OBSERVE))

    assert {a["projeto_slug"] for a in adrs["referencias"]} == {"workdev-core", "outro"}
    assert {d["projeto_slug"] for d in decisoes["referencias"]} == {"workdev-core", "outro"}


def test_listagem_com_projeto_inexistente_da_erro(db):
    saida = json.loads(ai.executar_tool("listar_adrs", {"projeto_slug": "nao-existe"},
                                        db, aut.OBSERVE))

    assert saida["erro"]
    assert saida["code"] == "nao_encontrado"


def test_listagem_respeita_o_limite_pedido(db):
    for indice in range(10):
        db.add(Decision(id=uuid4(), project_id=db.projeto.id,
                        title=f"Decisão {indice}", description="texto"))
    db.commit()

    saida = json.loads(ai.executar_tool("listar_decisoes",
                                        {"projeto_slug": "workdev-core", "limite": 3},
                                        db, aut.OBSERVE))

    assert saida["total"] == 3


def test_listagem_ignora_limite_absurdo(db):
    saida = json.loads(ai.executar_tool("listar_adrs", {"limite": 100000}, db, aut.OBSERVE))

    assert saida["total"] <= ai.MAX_LISTAGEM_REFERENCIAS


# --------------------------------------------------------------------------
# Portão de autoridade
# --------------------------------------------------------------------------


def test_listagens_sao_do_nivel_observe():
    assert aut.permite(aut.OBSERVE, "listar_adrs")
    assert aut.permite(aut.OBSERVE, "listar_decisoes")
    nomes = {t["name"] for t in aut.tools_para(aut.OBSERVE, ai.TOOLS)}
    assert {"listar_adrs", "listar_decisoes"} <= nomes


def test_listagem_e_bloqueada_quando_o_nivel_nao_alcanca(db):
    """Nível insuficiente bloqueia a execução — a tool não roda, não degrada."""
    with patch.dict(aut.NIVEL_POR_TOOL, {"listar_adrs": aut.PLAN}):
        saida = json.loads(ai.executar_tool("listar_adrs", {}, db, aut.OBSERVE))

    assert saida["executado"] is False
    assert saida["autoridade_atual"] == aut.OBSERVE
    assert saida["autoridade_necessaria"] == aut.PLAN


def test_tool_sem_classificacao_e_bloqueada(db):
    with patch.dict(aut.NIVEL_POR_TOOL, {}, clear=True):
        saida = json.loads(ai.executar_tool("listar_decisoes", {}, db, aut.OBSERVE))

    assert saida["executado"] is False
    assert saida["autoridade_necessaria"] == aut.ADMIN


def test_listagem_nao_escreve_no_banco(db):
    ai.executar_tool("listar_adrs", {}, db, aut.OBSERVE)
    ai.executar_tool("listar_decisoes", {}, db, aut.OBSERVE)

    assert len(db.new) == 0
    assert not db.dirty
