"""Regressões da recomendação consultiva de agente/modelo do PLAN.

O WorkDev recomenda; quem decide é o usuário. Estes testes travam o contrato:
preço vem do Model Catalog, cota nunca é inventada e capacidade não é
sacrificada por custo.
"""

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from app.services.agent_recommendation import (
    AGENT_LABELS,
    SUPPORTED_AGENTS,
    detect_quota_blocks,
    recommend_agents,
)


def catalog_row(
    *,
    catalog_id,
    display_name,
    provider,
    provider_model_id,
    category,
    capabilities,
    input_cost=None,
    output_cost=None,
    context_window=None,
    active=True,
    is_free=False,
    requires_confirmation=False,
    agent_slug=None,
    agent_preference_rank=None,
):
    return SimpleNamespace(
        id=catalog_id,
        display_name=display_name,
        provider=provider,
        provider_model_id=provider_model_id,
        category=category,
        capabilities=capabilities,
        input_cost_per_million=input_cost,
        output_cost_per_million=output_cost,
        context_window=context_window,
        allowed_reasoning_efforts=[],
        active=active,
        is_free=is_free,
        requires_confirmation=requires_confirmation,
        agent_slug=agent_slug,
        agent_preference_rank=agent_preference_rank,
    )


def catalog_db(rows):
    """DB fake que só responde ao catálogo (a recomendação não escreve nada)."""
    db = Mock()
    db.query.return_value.all.return_value = rows
    return db


def runtime(**states):
    """Snapshot de sessões: True = rodando, False = offline, None = não sondado."""
    snapshot = {}
    for agent in SUPPORTED_AGENTS:
        state = states.get(agent, True)
        if state is None:
            snapshot[agent] = {
                "agent": agent,
                "checked": False,
                "running": None,
                "health": None,
                "error": "tmux indisponível",
            }
        else:
            snapshot[agent] = {
                "agent": agent,
                "checked": True,
                "running": bool(state),
                "health": "idle" if state else "offline",
            }
    return snapshot


# Catálogo de referência dos testes: preços e categorias vivem AQUI, como no
# banco — nunca dentro do serviço de recomendação.
CATALOG = [
    catalog_row(
        catalog_id="openai-luna",
        display_name="GPT-5.6 Luna",
        provider="openai",
        provider_model_id="gpt-5.6-luna",
        category="economic",
        capabilities=["code", "reasoning", "review"],
        input_cost=0.20,
        output_cost=0.80,
        context_window=400000,
    ),
    catalog_row(
        catalog_id="openai-sol",
        display_name="GPT-5.6 Sol",
        provider="openai",
        provider_model_id="gpt-5.6-sol",
        category="premium",
        capabilities=[
            "code",
            "deep_reasoning",
            "review",
            "audit",
            "architecture",
        ],
        input_cost=3.00,
        output_cost=15.00,
        requires_confirmation=True,
    ),
    catalog_row(
        catalog_id="anthropic-opus",
        display_name="Claude Opus 5",
        provider="anthropic",
        provider_model_id="claude-opus-5",
        category="premium",
        capabilities=[
            "code",
            "deep_reasoning",
            "review",
            "audit",
            "architecture",
            "repository_analysis",
        ],
        input_cost=5.00,
        output_cost=25.00,
        requires_confirmation=True,
    ),
    catalog_row(
        catalog_id="gemini-flash",
        display_name="Gemini 2.5 Flash",
        provider="gemini",
        provider_model_id="gemini-2.5-flash",
        category="economic",
        capabilities=[
            "code",
            "reasoning",
            "review",
            "multimodal",
            "large_context",
        ],
        input_cost=0.15,
        output_cost=0.60,
        context_window=1000000,
    ),
    catalog_row(
        catalog_id="kimi-code",
        display_name="Kimi K2.7 Code",
        provider="openrouter",
        provider_model_id="moonshotai/kimi-k2.7-code",
        category="economic",
        capabilities=["code", "repository_analysis", "reasoning", "multimodal"],
        input_cost=0.66,
        output_cost=3.40,
        context_window=262144,
    ),
    catalog_row(
        catalog_id="qwen-coder",
        display_name="Qwen3 Coder",
        provider="openrouter",
        provider_model_id="qwen/qwen3-coder",
        category="economic",
        capabilities=["code"],
        input_cost=0.30,
        output_cost=1.00,
        context_window=262144,
    ),
]


SIMPLE_CODE_TASK = {
    "title": "Corrigir label do botão Salvar",
    "description": "Trocar o texto do botão no componente React",
    "priority": "low",
}
SIMPLE_CODE_PLAN = {
    "objective": "Ajustar o texto da interface",
    "constraints": [],
    "acceptance_criteria": ["texto corrigido"],
    "validation_steps": ["conferir tela"],
}

ARCHITECTURE_TASK = {
    "title": "Revisar arquitetura de integração entre módulos",
    "description": (
        "Avaliar service boundary, revisar dependências cross-module do "
        "repositório e registrar um ADR"
    ),
    "priority": "high",
}
ARCHITECTURE_PLAN = {
    "objective": "Definir a arquitetura alvo",
    "constraints": ["sem breaking change"],
    "acceptance_criteria": ["ADR publicado"],
    "validation_steps": ["revisão técnica"],
}

IMPLEMENTATION_TASK = {
    "title": "Implementar endpoint CRUD de subtasks",
    "description": (
        "Backend FastAPI e frontend React, corrigir bug do formulário e "
        "cobrir com testes"
    ),
    "priority": "medium",
}
IMPLEMENTATION_PLAN = {
    "objective": "Entregar o CRUD completo de subtasks",
    "constraints": ["manter contrato atual"],
    "acceptance_criteria": ["endpoint funcionando", "testes passando"],
    "validation_steps": ["pytest", "build do frontend"],
}

LARGE_CONTEXT_TASK = {
    "title": "Sintetizar PDFs e diagramas do inventário",
    "description": (
        "Comparar diagramas, screenshots e PDFs de grande volume e sumarizar "
        "o contexto extenso em um relatório único"
    ),
    "priority": "medium",
}
LARGE_CONTEXT_PLAN = {
    "objective": "Consolidar grande volume de material",
    "constraints": [],
    "acceptance_criteria": ["síntese entregue"],
    "validation_steps": ["conferir amostra"],
}

CRITICAL_TASK = {
    "title": "Migração de banco em produção com RLS e deploy",
    "description": "Alterar schema, autenticação e preparar rollback",
    "priority": "critical",
}
CRITICAL_PLAN = {
    "objective": "Executar migration segura",
    "constraints": ["preservar dados"],
    "acceptance_criteria": ["sem perda de dados"],
    "validation_steps": ["testar rollback"],
}


class RecommendationFitTest(unittest.TestCase):
    def test_plan_simples_de_codigo_recomenda_opcao_economica_adequada(self):
        result = recommend_agents(
            catalog_db(CATALOG),
            SIMPLE_CODE_TASK,
            SIMPLE_CODE_PLAN,
            [],
            runtime=runtime(),
        )

        recommended = result["recommended"]

        self.assertEqual(result["complexity"], "low")
        self.assertTrue(recommended["capable"])
        self.assertIn(
            recommended["cost_class"],
            {"free", "economic", "moderate"},
        )
        self.assertNotEqual(recommended["cost_class"], "premium")
        self.assertFalse(recommended["requires_confirmation"])

    def test_plan_complexo_nao_escolhe_modelo_barato_incapaz(self):
        result = recommend_agents(
            catalog_db(CATALOG),
            CRITICAL_TASK,
            CRITICAL_PLAN,
            [],
            runtime=runtime(),
        )

        recommended = result["recommended"]
        by_agent = {
            option["agent"]: option for option in result["options"]
        }

        self.assertEqual(result["complexity"], "critical")
        self.assertNotEqual(recommended["agent"], "qwen")
        self.assertTrue(recommended["capable"])

        # O modelo mais barato do catálogo não cobre auditoria/deep_reasoning:
        # ele não pode ser apresentado como adequado a uma task crítica.
        self.assertFalse(by_agent["qwen"]["capable"])

    def test_plan_arquitetural_pode_recomendar_claude_code(self):
        result = recommend_agents(
            catalog_db(CATALOG),
            ARCHITECTURE_TASK,
            ARCHITECTURE_PLAN,
            [],
            runtime=runtime(),
        )

        self.assertEqual(result["recommended"]["agent"], "claude")
        self.assertEqual(
            result["recommended"]["agent_label"],
            "Claude Code",
        )

    def test_plan_de_implementacao_pode_recomendar_codex(self):
        result = recommend_agents(
            catalog_db(CATALOG),
            IMPLEMENTATION_TASK,
            IMPLEMENTATION_PLAN,
            [],
            runtime=runtime(),
        )

        self.assertEqual(result["recommended"]["agent"], "codex")

    def test_contexto_muito_grande_favorece_gemini(self):
        result = recommend_agents(
            catalog_db(CATALOG),
            LARGE_CONTEXT_TASK,
            LARGE_CONTEXT_PLAN,
            [],
            runtime=runtime(),
        )

        self.assertEqual(result["recommended"]["agent"], "gemini")

    def test_usuario_continua_podendo_escolher_qualquer_um_dos_cinco(self):
        result = recommend_agents(
            catalog_db(CATALOG),
            IMPLEMENTATION_TASK,
            IMPLEMENTATION_PLAN,
            [],
            runtime=runtime(),
        )

        agents = [option["agent"] for option in result["options"]]

        self.assertEqual(sorted(agents), sorted(SUPPORTED_AGENTS))
        self.assertEqual(len(agents), 5)

        for option in result["options"]:
            self.assertEqual(
                option["agent_label"],
                AGENT_LABELS[option["agent"]],
            )


class RecommendationCostTest(unittest.TestCase):
    def test_preco_vem_do_model_catalog_e_nao_de_constante(self):
        baseline = recommend_agents(
            catalog_db(CATALOG),
            IMPLEMENTATION_TASK,
            IMPLEMENTATION_PLAN,
            [],
            runtime=runtime(),
        )

        codex_baseline = next(
            option
            for option in baseline["options"]
            if option["agent"] == "codex"
        )

        self.assertEqual(codex_baseline["cost_class"], "economic")
        self.assertEqual(baseline["pricing_source"], "ai_model_catalog")

        # Mesmo código, catálogo diferente: o custo tem que acompanhar o dado.
        reclassified = [
            catalog_row(
                catalog_id=row.id,
                display_name=row.display_name,
                provider=row.provider,
                provider_model_id=row.provider_model_id,
                category=(
                    "premium" if row.id == "openai-luna" else row.category
                ),
                capabilities=row.capabilities,
                input_cost=row.input_cost_per_million,
                output_cost=row.output_cost_per_million,
                context_window=row.context_window,
                active=row.active,
                is_free=row.is_free,
                requires_confirmation=(
                    True
                    if row.id == "openai-luna"
                    else row.requires_confirmation
                ),
            )
            for row in CATALOG
        ]

        changed = recommend_agents(
            catalog_db(reclassified),
            IMPLEMENTATION_TASK,
            IMPLEMENTATION_PLAN,
            [],
            runtime=runtime(),
        )

        codex_changed = next(
            option
            for option in changed["options"]
            if option["agent"] == "codex"
        )

        self.assertEqual(codex_changed["cost_class"], "premium")
        self.assertEqual(
            codex_changed["price_index"],
            str(row_price("openai-luna")),
        )

    def test_entre_suficientes_prefere_o_mais_barato(self):
        rows = [
            catalog_row(
                catalog_id="gemini-caro",
                display_name="Gemini Caro",
                provider="gemini",
                provider_model_id="gemini-caro",
                category="economic",
                capabilities=["code", "reasoning"],
                input_cost=2.00,
                output_cost=8.00,
            ),
            catalog_row(
                catalog_id="gemini-barato",
                display_name="Gemini Barato",
                provider="gemini",
                provider_model_id="gemini-barato",
                category="economic",
                capabilities=["code", "reasoning"],
                input_cost=0.10,
                output_cost=0.40,
            ),
        ]

        result = recommend_agents(
            catalog_db(rows),
            IMPLEMENTATION_TASK,
            IMPLEMENTATION_PLAN,
            [],
            runtime=runtime(),
        )

        gemini = next(
            option
            for option in result["options"]
            if option["agent"] == "gemini"
        )

        self.assertEqual(gemini["catalog_id"], "gemini-barato")


class RecommendationAvailabilityTest(unittest.TestCase):
    def test_modelo_inativo_nao_e_recomendado_como_disponivel(self):
        rows = [
            catalog_row(
                catalog_id="qwen-coder",
                display_name="Qwen3 Coder",
                provider="openrouter",
                provider_model_id="qwen/qwen3-coder",
                category="economic",
                capabilities=["code"],
                input_cost=0.30,
                output_cost=1.00,
                active=False,
            ),
            *[row for row in CATALOG if row.id != "qwen-coder"],
        ]

        result = recommend_agents(
            catalog_db(rows),
            SIMPLE_CODE_TASK,
            SIMPLE_CODE_PLAN,
            [],
            runtime=runtime(),
        )

        qwen = next(
            option
            for option in result["options"]
            if option["agent"] == "qwen"
        )

        self.assertEqual(qwen["availability"], "unavailable")
        self.assertEqual(
            qwen["availability_reason"],
            "sem modelo ativo no catálogo",
        )
        self.assertIsNone(qwen["model"])
        self.assertNotEqual(
            result["recommended"]["agent"],
            "qwen",
        )

    def test_sem_cota_conhecida_nao_inventa_saldo(self):
        result = recommend_agents(
            catalog_db(CATALOG),
            IMPLEMENTATION_TASK,
            IMPLEMENTATION_PLAN,
            [],
            runtime=runtime(),
        )

        recommended = result["recommended"]

        self.assertEqual(recommended["quota"], "unknown")
        self.assertEqual(recommended["quota_label"], "não verificada")
        self.assertIsNone(recommended["quota_reason"])

        for option in result["options"]:
            self.assertEqual(option["quota"], "unknown")

    def test_runtime_nao_sondado_fica_nao_verificada(self):
        result = recommend_agents(
            catalog_db(CATALOG),
            IMPLEMENTATION_TASK,
            IMPLEMENTATION_PLAN,
            [],
            runtime=runtime(codex=None),
        )

        codex = next(
            option
            for option in result["options"]
            if option["agent"] == "codex"
        )

        self.assertEqual(codex["availability"], "unknown")
        self.assertEqual(codex["availability_label"], "não verificada")

    def test_erro_real_de_cota_oferece_alternativa_disponivel(self):
        result = recommend_agents(
            catalog_db(CATALOG),
            IMPLEMENTATION_TASK,
            IMPLEMENTATION_PLAN,
            [],
            runtime=runtime(),
            quota_signals={
                "codex": (
                    "erro registrado na execução: insufficient_quota: "
                    "You exceeded your current quota"
                ),
            },
        )

        recommended = result["recommended"]
        alternative = result["alternative"]

        self.assertEqual(recommended["agent"], "codex")
        self.assertEqual(recommended["quota"], "exhausted")
        self.assertEqual(recommended["availability"], "unavailable")
        self.assertIn("quota", recommended["availability_reason"])

        self.assertIsNotNone(alternative)
        self.assertNotEqual(alternative["agent"], "codex")
        self.assertEqual(alternative["availability"], "available")
        self.assertEqual(alternative["quota"], "unknown")


class QuotaDetectionTest(unittest.TestCase):
    def test_detecta_apenas_erro_real_registrado(self):
        now = datetime.now(timezone.utc)

        runs = [
            SimpleNamespace(
                agent="codex",
                status="failed",
                error="429 insufficient_quota: exceeded current quota",
                updated_at=now - timedelta(hours=1),
            ),
            SimpleNamespace(
                agent="kimi",
                status="failed",
                error="Runtime AUTO encerrou antes de registrar resultado",
                updated_at=now - timedelta(hours=2),
            ),
        ]

        db = Mock()
        chain = (
            db.query.return_value.filter.return_value
            .order_by.return_value.limit.return_value
        )
        chain.all.side_effect = [runs, []]

        blocked = detect_quota_blocks(db, now=now)

        self.assertIn("codex", blocked)
        self.assertNotIn("kimi", blocked)
        self.assertIn("quota", blocked["codex"])

    def test_sem_erro_registrado_nada_e_bloqueado(self):
        db = Mock()
        chain = (
            db.query.return_value.filter.return_value
            .order_by.return_value.limit.return_value
        )
        chain.all.side_effect = [[], []]

        self.assertEqual(detect_quota_blocks(db), {})


# Modelos permitidos por agente, como a migration os vincula.
CLAUDE_MODELS = [
    catalog_row(
        catalog_id="anthropic-opus-5",
        display_name="Claude Opus 5",
        provider="anthropic",
        provider_model_id="claude-opus-5",
        category="premium",
        capabilities=[
            "code", "architecture", "repository_analysis", "review",
            "reasoning", "deep_reasoning", "audit", "agentic",
            "large_context",
        ],
        input_cost=5.00,
        output_cost=25.00,
        context_window=1000000,
        requires_confirmation=True,
        agent_slug="claude",
        agent_preference_rank=1,
    ),
    catalog_row(
        catalog_id="anthropic-sonnet-5",
        display_name="Claude Sonnet 5",
        provider="anthropic",
        provider_model_id="claude-sonnet-5",
        category="premium",
        capabilities=[
            "code", "architecture", "repository_analysis", "review",
            "reasoning", "agentic", "large_context",
        ],
        input_cost=3.00,
        output_cost=15.00,
        context_window=1000000,
        requires_confirmation=True,
        agent_slug="claude",
        agent_preference_rank=2,
    ),
]

# Codex é o caso sem preço publicado: só o rank ordena.
CODEX_MODELS = [
    catalog_row(
        catalog_id="openai-sol",
        display_name="GPT-5.6 Sol",
        provider="openai",
        provider_model_id="gpt-5.6-sol",
        category="premium",
        capabilities=[
            "deep_reasoning", "audit", "code", "architecture",
            "repository_analysis", "review", "reasoning", "agentic",
        ],
        requires_confirmation=True,
        agent_slug="codex",
        agent_preference_rank=1,
    ),
    catalog_row(
        catalog_id="openai-terra",
        display_name="GPT-5.6 Terra",
        provider="openai",
        provider_model_id="gpt-5.6-terra",
        category="premium",
        capabilities=["reasoning", "review", "code"],
        requires_confirmation=True,
        agent_slug="codex",
        agent_preference_rank=2,
    ),
]

KIMI_MODELS = [
    catalog_row(
        catalog_id="openrouter-kimi-k3",
        display_name="Kimi K3",
        provider="openrouter",
        provider_model_id="moonshotai/kimi-k3",
        category="premium",
        capabilities=[
            "multimodal", "agentic", "code", "repository_analysis",
            "reasoning", "review", "large_context",
        ],
        input_cost=3.00,
        output_cost=15.00,
        context_window=1048576,
        requires_confirmation=True,
        agent_slug="kimi",
        agent_preference_rank=1,
    ),
    catalog_row(
        catalog_id="openrouter-kimi-k2-7-code",
        display_name="Kimi K2.7 Code",
        provider="openrouter",
        provider_model_id="moonshotai/kimi-k2.7-code",
        category="economic",
        capabilities=["code", "repository_analysis", "reasoning"],
        input_cost=0.71,
        output_cost=3.50,
        context_window=262144,
        agent_slug="kimi",
        agent_preference_rank=2,
    ),
]

# Qwen Code roda o 3.5 397B A17B pela OpenRouter. Preço e contexto vêm do
# catálogo público da OpenRouter, não de constante no código.
QWEN_MODEL = catalog_row(
    catalog_id="openrouter-qwen3-5-397b-a17b",
    display_name="Qwen3.5 397B A17B",
    provider="openrouter",
    provider_model_id="qwen/qwen3.5-397b-a17b",
    category="economic",
    capabilities=["code", "reasoning", "multimodal"],
    input_cost=0.39,
    output_cost=2.34,
    context_window=262144,
    agent_slug="qwen",
    agent_preference_rank=1,
)

# Continua no catálogo servindo o AI Hub, mas sem vínculo com o agente.
QWEN_CATALOG_ONLY = catalog_row(
    catalog_id="openrouter-qwen3-coder",
    display_name="Qwen3 Coder",
    provider="openrouter",
    provider_model_id="qwen/qwen3-coder",
    category="economic",
    capabilities=["code", "prompt_generation"],
    input_cost=0.30,
    output_cost=1.00,
    context_window=262144,
)

CONFIGURED = (
    CLAUDE_MODELS + CODEX_MODELS + KIMI_MODELS
    + [QWEN_MODEL, QWEN_CATALOG_ONLY]
)


class AgentAllowedModelsTest(unittest.TestCase):
    """O agente é recomendado primeiro; o modelo vem do que ele pode rodar."""

    def option(self, agent, task, plan, rows=None):
        result = recommend_agents(
            catalog_db(rows if rows is not None else CONFIGURED),
            task,
            plan,
            [],
            runtime=runtime(),
        )
        return next(
            item
            for item in result["options"]
            if item["agent"] == agent
        )

    def test_so_lista_os_modelos_permitidos_do_agente(self):
        claude = self.option(
            "claude", ARCHITECTURE_TASK, ARCHITECTURE_PLAN
        )

        modelos = {model["model"] for model in claude["models"]}

        self.assertEqual(
            modelos,
            {"claude-opus-5", "claude-sonnet-5"},
        )
        # Nunca o catálogo inteiro: nada de Kimi, Codex ou Qwen aqui.
        self.assertNotIn("gpt-5.6-sol", modelos)
        self.assertNotIn("qwen/qwen3-coder", modelos)

    def test_claude_usa_opus_5_em_trabalho_complexo(self):
        claude = self.option(
            "claude", CRITICAL_TASK, CRITICAL_PLAN
        )

        self.assertEqual(claude["model"], "claude-opus-5")
        self.assertTrue(claude["capable"])

        recomendado = [
            model
            for model in claude["models"]
            if model["recommended"]
        ]
        self.assertEqual(len(recomendado), 1)
        self.assertEqual(recomendado[0]["model"], "claude-opus-5")

    def test_claude_usa_sonnet_5_quando_o_custo_justifica(self):
        claude = self.option(
            "claude", SIMPLE_CODE_TASK, SIMPLE_CODE_PLAN
        )

        self.assertEqual(claude["model"], "claude-sonnet-5")
        self.assertTrue(claude["capable"])

    def test_codex_usa_sol_na_complexidade_alta(self):
        codex = self.option(
            "codex", CRITICAL_TASK, CRITICAL_PLAN
        )

        self.assertEqual(codex["model"], "gpt-5.6-sol")

    def test_codex_usa_terra_sem_preco_publicado(self):
        """Sem preço no catálogo, o rank declarado indica a opção econômica."""
        codex = self.option(
            "codex", SIMPLE_CODE_TASK, SIMPLE_CODE_PLAN
        )

        self.assertEqual(codex["model"], "gpt-5.6-terra")
        self.assertIsNone(codex["price_index"])

    def test_kimi_usa_k3_na_complexidade_alta(self):
        kimi = self.option(
            "kimi", CRITICAL_TASK, CRITICAL_PLAN
        )

        self.assertEqual(kimi["model"], "moonshotai/kimi-k3")

    def test_kimi_usa_k2_7_como_alternativa_economica(self):
        kimi = self.option(
            "kimi", SIMPLE_CODE_TASK, SIMPLE_CODE_PLAN
        )

        self.assertEqual(kimi["model"], "moonshotai/kimi-k2.7-code")

    def test_qwen_usa_o_3_5_397b_pela_openrouter(self):
        qwen = self.option(
            "qwen", SIMPLE_CODE_TASK, SIMPLE_CODE_PLAN
        )

        self.assertEqual(qwen["provider"], "openrouter")
        self.assertEqual(qwen["model"], "qwen/qwen3.5-397b-a17b")
        self.assertEqual(qwen["context_window"], 262144)

    def test_qwen3_coder_segue_no_catalogo_mas_fora_do_agente(self):
        """O modelo antigo continua servindo o AI Hub, não o agente."""
        qwen = self.option(
            "qwen", SIMPLE_CODE_TASK, SIMPLE_CODE_PLAN
        )

        modelos = {model["model"] for model in qwen["models"]}

        self.assertEqual(modelos, {"qwen/qwen3.5-397b-a17b"})
        self.assertNotIn("qwen/qwen3-coder", modelos)

    def test_qwen_com_um_modelo_so_nao_gera_seletor(self):
        qwen = self.option(
            "qwen", SIMPLE_CODE_TASK, SIMPLE_CODE_PLAN
        )

        self.assertEqual(len(qwen["models"]), 1)
        self.assertTrue(qwen["models"][0]["recommended"])

    def test_preco_do_seletor_vem_do_catalogo(self):
        claude = self.option(
            "claude", ARCHITECTURE_TASK, ARCHITECTURE_PLAN
        )

        by_model = {
            model["model"]: model
            for model in claude["models"]
        }

        from decimal import Decimal

        self.assertEqual(
            Decimal(by_model["claude-opus-5"]["price_index"]),
            Decimal("30"),
        )
        self.assertEqual(
            Decimal(by_model["claude-sonnet-5"]["price_index"]),
            Decimal("18"),
        )
        for model in claude["models"]:
            self.assertIn("cost_label", model)
            self.assertIn("context_window", model)

    def test_modelo_permitido_vence_o_mais_barato_do_provider(self):
        """Kimi tem irmão mais barato sem vínculo; ele não pode ser sugerido."""
        intruso = catalog_row(
            catalog_id="openrouter-kimi-antigo",
            display_name="Kimi Antigo",
            provider="openrouter",
            provider_model_id="moonshotai/kimi-antigo",
            category="economic",
            capabilities=["code", "repository_analysis", "reasoning"],
            input_cost=0.01,
            output_cost=0.02,
        )

        kimi = self.option(
            "kimi",
            SIMPLE_CODE_TASK,
            SIMPLE_CODE_PLAN,
            rows=CONFIGURED + [intruso],
        )

        self.assertEqual(kimi["model"], "moonshotai/kimi-k2.7-code")

    def test_todos_os_permitidos_inativos_ficam_indisponiveis(self):
        inativos = [
            catalog_row(
                catalog_id=row.id,
                display_name=row.display_name,
                provider=row.provider,
                provider_model_id=row.provider_model_id,
                category=row.category,
                capabilities=row.capabilities,
                input_cost=row.input_cost_per_million,
                output_cost=row.output_cost_per_million,
                active=False,
                agent_slug="claude",
                agent_preference_rank=row.agent_preference_rank,
            )
            for row in CLAUDE_MODELS
        ]

        claude = self.option(
            "claude",
            ARCHITECTURE_TASK,
            ARCHITECTURE_PLAN,
            rows=inativos + CODEX_MODELS,
        )

        self.assertEqual(claude["availability"], "unavailable")
        self.assertEqual(
            claude["availability_reason"],
            "sem modelo ativo no catálogo",
        )
        self.assertIsNone(claude["model"])

    def test_vinculo_nao_dispensa_o_gate_de_capacidade(self):
        fraco = catalog_row(
            catalog_id="claude-fraco",
            display_name="Claude Fraco",
            provider="anthropic",
            provider_model_id="claude-fraco",
            category="premium",
            capabilities=["conversation"],
            input_cost=1.00,
            output_cost=2.00,
            agent_slug="claude",
            agent_preference_rank=1,
        )

        claude = self.option(
            "claude",
            CRITICAL_TASK,
            CRITICAL_PLAN,
            rows=[fraco] + CODEX_MODELS,
        )

        self.assertEqual(claude["model"], "claude-fraco")
        self.assertFalse(claude["capable"])

    def test_vinculo_atravessa_o_mapa_provider_agente(self):
        """Kimi vem de `openrouter`, que não mapeia agente sozinho."""
        kimi = self.option(
            "kimi", CRITICAL_TASK, CRITICAL_PLAN
        )

        self.assertEqual(kimi["provider"], "openrouter")
        self.assertEqual(kimi["context_window"], 1048576)


def row_price(catalog_id):
    from decimal import Decimal

    row = next(row for row in CATALOG if row.id == catalog_id)

    return Decimal(str(row.input_cost_per_million)) + Decimal(
        str(row.output_cost_per_million)
    )


if __name__ == "__main__":
    unittest.main()
