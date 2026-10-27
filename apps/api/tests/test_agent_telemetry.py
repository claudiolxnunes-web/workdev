"""Telemetria por AgentRun: o que se grava, o que não se grava e por quê.

O contrato que estes testes fixam:

- **não se inventa número**: sem contagem e sem custo, não há linha;
- **a origem vai junto**: `official` (veio do runtime) ou `estimated`
  (derivado do catálogo);
- **o dinheiro é classificado**: despesa marginal, assinatura, franquia ou
  runtime próprio não somam na mesma linha;
- **o agrupamento é por origem e classe**, senão a separação de que a
  tabela existe se desfaz no relatório.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services import agent_telemetry


class _DbFalso:
    """Sessão que responde o que a função perguntar, sem tocar o banco."""

    def __init__(self, resultado=None):
        self.resultado = resultado
        self.adicionados = []

    def query(self, *_a, **_k):
        return self

    def filter(self, *_a, **_k):
        return self

    def first(self):
        return self.resultado

    def get(self, *_a, **_k):
        return None

    def add(self, linha):
        self.adicionados.append(linha)

    def flush(self):
        return None


def _run(**kwargs):
    base = {"id": "run-1", "agent": "local-code", "provider": None, "model": None}
    base.update(kwargs)
    return type("Run", (), base)()


class TestClassificacaoDeCusto:
    def test_runtime_proprio_e_custo_local(self):
        assert agent_telemetry.custo_da_run("local-code", "gpu-hostinger") == "local"
        assert agent_telemetry.custo_da_run("local-code", "ollama") == "local"

    def test_cli_por_assinatura_nao_e_despesa_marginal(self):
        assert agent_telemetry.custo_da_run("claude", "anthropic") == "included_plan"
        assert agent_telemetry.custo_da_run("codex", "openai") == "included_plan"

    def test_api_por_token_e_despesa_marginal(self):
        assert agent_telemetry.custo_da_run("qwen", "openrouter") == "paid_api"
        assert agent_telemetry.custo_da_run("kimi", "moonshot") == "paid_api"


class TestRegistro:
    def test_sem_numero_nao_grava_linha(self):
        db = _DbFalso()

        linha = agent_telemetry.registrar(db, _run())

        assert linha is None
        assert db.adicionados == []

    def test_grava_com_origem_e_classe(self):
        db = _DbFalso()

        linha = agent_telemetry.registrar(
            db,
            _run(),
            agent="claude",
            provider="anthropic",
            model="claude-opus-5",
            input_tokens=1000,
            output_tokens=200,
        )

        assert linha is not None
        assert linha.input_tokens == 1000
        assert linha.output_tokens == 200
        assert linha.total_tokens == 1200
        assert linha.source == agent_telemetry.SOURCE_OFFICIAL
        assert linha.cost_class == agent_telemetry.COST_INCLUDED_PLAN
        assert linha.currency == "USD"

    def test_total_so_existe_com_token(self):
        db = _DbFalso()

        linha = agent_telemetry.registrar(
            db,
            _run(),
            input_tokens=10,
        )

        assert linha.total_tokens == 10

    def test_numero_negativo_e_ignorado(self):
        db = _DbFalso()

        linha = agent_telemetry.registrar(
            db,
            _run(),
            input_tokens=-5,
            output_tokens=None,
        )

        assert linha is None


class TestDespacho:
    def test_extrai_contagem_do_ollama(self):
        db = _DbFalso()

        linha = agent_telemetry.registrar_despacho(
            db,
            _run(),
            {
                "model": "qwen2.5-coder:14b",
                "prompt_eval_count": 1200,
                "eval_count": 340,
            },
            runtime_id="gpu-hostinger",
        )

        assert linha is not None
        assert linha.input_tokens == 1200
        assert linha.output_tokens == 340
        assert linha.source == agent_telemetry.SOURCE_OFFICIAL
        assert linha.cost_class == agent_telemetry.COST_LOCAL
        # Runtime próprio: não há cobrança por token.
        assert linha.estimated_cost == Decimal("0.000000")

    def test_extrai_contagem_do_llamacpp(self):
        db = _DbFalso()

        linha = agent_telemetry.registrar_despacho(
            db,
            _run(),
            {
                "model": "moe/q27/dev/fast",
                "input_tokens": 800,
                "output_tokens": 120,
            },
            runtime_id="local-code",
        )

        assert linha is not None
        assert linha.input_tokens == 800
        assert linha.output_tokens == 120

    def test_sem_contagem_nao_grava(self):
        db = _DbFalso()

        linha = agent_telemetry.registrar_despacho(
            db,
            _run(),
            {"model": "qwen2.5-coder:14b"},
            runtime_id="gpu-hostinger",
        )

        assert linha is None
        assert db.adicionados == []


class TestCustoDoCatalogo:
    def test_usa_preco_de_catalogo(self):
        linha = MagicMock()
        linha.input_cost_per_million = Decimal("3.000000")
        linha.output_cost_per_million = Decimal("15.000000")
        db = _DbFalso(linha)

        custo = agent_telemetry.custo_do_catalogo(
            db,
            "claude-opus-5",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )

        assert custo == Decimal("18.000000")

    def test_sem_preco_nao_inventa_numero(self):
        linha = MagicMock()
        linha.input_cost_per_million = None
        linha.output_cost_per_million = None
        db = _DbFalso(linha)

        assert agent_telemetry.custo_do_catalogo(db, "modelo-desconhecido") is None

    def test_modelo_inexistente_devolve_none(self):
        db = _DbFalso(None)

        assert agent_telemetry.custo_do_catalogo(db, "nao-existe") is None


class TestConsultaDeResumo:
    def _sql(self, **filtros):
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            consulta = agent_telemetry.consulta_resumo(db, **filtros)
            return str(consulta.statement.compile(compile_kwargs={"literal_binds": True}))
        finally:
            db.close()

    def test_agrupa_por_origem_e_classe(self):
        sql = self._sql()

        assert "GROUP BY" in sql
        assert "agent_run_telemetry.source" in sql
        assert "agent_run_telemetry.cost_class" in sql
        assert "agent_run_telemetry.agent" in sql

    def test_filtro_por_projeto_entra_no_sql(self):
        from uuid import UUID

        sql = self._sql(project_id=str(UUID("11111111-1111-1111-1111-111111111111")))

        assert "agent_run_telemetry.project_id" in sql


class TestRotas:
    def test_resumo_devolve_as_linhas(self):
        from app.routers import handoffs

        with patch.object(
            agent_telemetry,
            "resumo",
            return_value=[{"agent": "local-code", "calls": 2}],
        ) as resumo:
            resposta = handoffs.get_telemetry_summary(db=MagicMock())

        resumo.assert_called_once()
        assert resposta["rows"] == [{"agent": "local-code", "calls": 2}]

    def test_run_sem_consumo_marca_nao_reportado(self):
        from app.routers import handoffs

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        with patch.object(
            handoffs,
            "_get_run",
            return_value=_run(provider="anthropic", model="claude-opus-5"),
        ):
            resposta = handoffs.get_run_telemetry("run-1", db=db)

        assert resposta["reported"] is False
        assert resposta["telemetry"] == []
        assert resposta["provider"] == "anthropic"


@pytest.mark.parametrize(
    "source,esperado",
    [
        (agent_telemetry.SOURCE_OFFICIAL, "official"),
        (agent_telemetry.SOURCE_ESTIMATED, "estimated"),
    ],
)
def test_fontes_conhecidas(source, esperado):
    assert source == esperado
