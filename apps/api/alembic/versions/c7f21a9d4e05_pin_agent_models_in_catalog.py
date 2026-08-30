"""Modelos permitidos por agente, com recomendado por ordem de capacidade.

O PLAN recomenda o agente; o modelo é informação associada ao agente
configurado. Antes disto a recomendação escolhia o modelo mais barato do
provider inteiro, e o card prometia um modelo que a CLI não roda.

Três conceitos, e só dois precisam de schema novo:

  1. modelos PERMITIDOS por agente  -> `agent_slug`
  2. modelo RECOMENDADO/padrão      -> `agent_preference_rank` (1 = recomendado)
  3. modelo ESCOLHIDO pelo usuário  -> `agent_runs.model`, que JÁ EXISTE

O rank existe porque nem todo provider publica preço no catálogo (as linhas
OpenAI têm preço NULL): sem preço não há como ordenar por custo, então a ordem
de capacidade é declarada pelo operador.

Linhas sem `agent_slug` continuam no catálogo servindo o AI Hub normalmente.
Qwen não é tocado aqui e mantém exatamente o comportamento atual.

Revision ID: c7f21a9d4e05
Revises: bbc43d885005
Create Date: 2026-08-30
"""

import json

import sqlalchemy as sa
from alembic import op


revision = "c7f21a9d4e05"
down_revision = "bbc43d885005"
branch_labels = None
depends_on = None


# (agente, provider, provider_model_id, rank) — rank 1 = recomendado/padrão.
AGENT_MODELS = (
    ("claude", "anthropic", "claude-opus-5", 1),
    ("claude", "anthropic", "claude-sonnet-5", 2),
    ("codex", "openai", "gpt-5.6-sol", 1),
    ("codex", "openai", "gpt-5.6-terra", 2),
    ("kimi", "openrouter", "moonshotai/kimi-k3", 1),
    ("kimi", "openrouter", "moonshotai/kimi-k2.7-code", 2),
    ("gemini", "gemini", "gemini-3.5-flash", 1),
    ("qwen", "openrouter", "qwen/qwen3.5-397b-a17b", 1),
)


# Capacidades reais dos modelos que as CLIs de engenharia rodam. O catálogo
# não as declarava, e por isso agentes de código apareciam como inadequados.
CAPABILITY_FIXES = {
    "openai-sol": [
        "deep_reasoning", "audit", "code", "architecture",
        "repository_analysis", "review", "reasoning", "agentic",
    ],
    "openai-terra": ["reasoning", "review", "code"],
    "gemini-3-5-flash": [
        "deep_reasoning", "code", "review", "multimodal", "agentic",
        "architecture", "repository_analysis", "reasoning", "large_context",
    ],
    "openrouter-kimi-k3": [
        "multimodal", "agentic", "code", "repository_analysis",
        "reasoning", "review", "large_context",
    ],
    "openrouter-kimi-k2-7-code": [
        "code", "repository_analysis", "reasoning", "multimodal",
    ],
}


CAPABILITY_ROLLBACK = {
    "openai-sol": ["deep_reasoning", "audit"],
    "openai-terra": ["reasoning", "review"],
    "gemini-3-5-flash": [
        "deep_reasoning", "code", "review", "multimodal", "agentic",
    ],
    "openrouter-kimi-k3": ["multimodal", "agentic"],
    "openrouter-kimi-k2-7-code": ["code", "repository_analysis"],
}


ANTHROPIC_MODELS = (
    (
        "anthropic-opus-5", "Claude Opus 5", "claude-opus-5",
        [
            "code", "architecture", "repository_analysis", "review",
            "reasoning", "deep_reasoning", "audit", "agentic", "large_context",
        ],
        5.000000, 25.000000,
    ),
    (
        "anthropic-sonnet-5", "Claude Sonnet 5", "claude-sonnet-5",
        [
            "code", "architecture", "repository_analysis", "review",
            "reasoning", "agentic", "large_context",
        ],
        3.000000, 15.000000,
    ),
)


# Qwen Code roda este modelo pela OpenRouter. Preço, janela de contexto e
# modalidades vêm do catálogo público da OpenRouter (`/api/v1/models`), que é
# a mesma fonte que a conta do operador exibe. Nada estimado.
QWEN_MODEL = {
    "id": "openrouter-qwen3-5-397b-a17b",
    "display_name": "Qwen3.5 397B A17B",
    "provider_model_id": "qwen/qwen3.5-397b-a17b",
    "capabilities": ["code", "reasoning", "multimodal"],
    "context_window": 262144,
    "input_cost": 0.390000,
    "output_cost": 2.340000,
}


# Preços e modalidades conferidos contra o catálogo público da OpenRouter
# (`/api/v1/models`) em 2026-08-30. O K2.7 estava com preço de 2026-08-19,
# defasado; o K3 já batia. Ninguém estima preço aqui.
OPENROUTER_REFRESH = (
    # (catalog_id, input, output, context_window, supports_multimodal)
    ("openrouter-kimi-k2-7-code", 0.660000, 3.400000, 262144, True),
    ("openrouter-kimi-k3", 3.000000, 15.000000, 1048576, True),
)


OPENROUTER_REFRESH_ROLLBACK = (
    ("openrouter-kimi-k2-7-code", 0.710000, 3.500000, 262144, False),
    ("openrouter-kimi-k3", 3.000000, 15.000000, 1048576, True),
)


def _refresh_pricing(rows) -> None:
    for (
        catalog_id, input_cost, output_cost, context_window, multimodal,
    ) in rows:
        op.execute(
            sa.text(
                """
                UPDATE ai_model_catalog
                   SET input_cost_per_million  = :input_cost,
                       output_cost_per_million = :output_cost,
                       context_window          = :context_window,
                       supports_multimodal     = :multimodal,
                       pricing_updated_at      = '2026-08-30T00:00:00Z',
                       updated_at              = now()
                 WHERE id = :catalog_id
                """
            ).bindparams(
                catalog_id=catalog_id,
                input_cost=input_cost,
                output_cost=output_cost,
                context_window=context_window,
                multimodal=multimodal,
            )
        )


def _set_capabilities(mapping) -> None:
    for catalog_id, capabilities in mapping.items():
        op.execute(
            sa.text(
                """
                UPDATE ai_model_catalog
                   SET capabilities = CAST(:capabilities AS jsonb),
                       updated_at = now()
                 WHERE id = :catalog_id
                """
            ).bindparams(
                capabilities=json.dumps(capabilities),
                catalog_id=catalog_id,
            )
        )


def upgrade() -> None:
    op.add_column(
        "ai_model_catalog",
        sa.Column("agent_slug", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "ai_model_catalog",
        sa.Column("agent_preference_rank", sa.SmallInteger(), nullable=True),
    )

    op.create_unique_constraint(
        "uq_ai_model_agent_rank",
        "ai_model_catalog",
        ["agent_slug", "agent_preference_rank"],
    )
    op.create_check_constraint(
        "ck_ai_model_agent_rank_pair",
        "ai_model_catalog",
        "(agent_slug IS NULL) = (agent_preference_rank IS NULL)",
    )
    op.create_check_constraint(
        "ck_ai_model_agent_rank_positive",
        "ai_model_catalog",
        "agent_preference_rank IS NULL OR agent_preference_rank >= 1",
    )

    # Claude Code roda Opus 5 e Sonnet 5. Preços e janela de contexto vêm da
    # tabela oficial de modelos da Anthropic; nada hardcoded na aplicação.
    for (
        catalog_id, display_name, provider_model_id,
        capabilities, input_cost, output_cost,
    ) in ANTHROPIC_MODELS:
        op.execute(
            sa.text(
                """
                INSERT INTO ai_model_catalog (
                    id, display_name, provider, provider_model_id, category,
                    capabilities, allowed_reasoning_efforts, context_window,
                    input_cost_per_million, output_cost_per_million,
                    supports_tools, supports_structured_output,
                    supports_multimodal, active, is_free,
                    requires_confirmation, allowed_fallbacks,
                    pricing_updated_at
                ) VALUES (
                    :catalog_id, :display_name, 'anthropic',
                    :provider_model_id, 'premium',
                    CAST(:capabilities AS jsonb),
                    '["low","medium","high","xhigh","max"]',
                    1000000, :input_cost, :output_cost,
                    true, true, true, true, false, true,
                    '[]', '2026-08-30T00:00:00Z'
                )
                ON CONFLICT (provider, provider_model_id) DO UPDATE SET
                    capabilities              = EXCLUDED.capabilities,
                    allowed_reasoning_efforts = EXCLUDED.allowed_reasoning_efforts,
                    context_window            = EXCLUDED.context_window,
                    input_cost_per_million    = EXCLUDED.input_cost_per_million,
                    output_cost_per_million   = EXCLUDED.output_cost_per_million,
                    active                    = true,
                    pricing_updated_at        = EXCLUDED.pricing_updated_at,
                    updated_at                = now()
                """
            ).bindparams(
                catalog_id=catalog_id,
                display_name=display_name,
                provider_model_id=provider_model_id,
                capabilities=json.dumps(capabilities),
                input_cost=input_cost,
                output_cost=output_cost,
            )
        )

    op.execute(
        sa.text(
            """
            INSERT INTO ai_model_catalog (
                id, display_name, provider, provider_model_id, category,
                capabilities, allowed_reasoning_efforts, context_window,
                input_cost_per_million, output_cost_per_million,
                supports_tools, supports_structured_output,
                supports_multimodal, active, is_free, requires_confirmation,
                allowed_fallbacks, pricing_updated_at
            ) VALUES (
                :catalog_id, :display_name, 'openrouter',
                :provider_model_id, 'economic',
                CAST(:capabilities AS jsonb), '[]',
                :context_window, :input_cost, :output_cost,
                true, true, true, true, false, false,
                '[]', '2026-08-30T00:00:00Z'
            )
            ON CONFLICT (provider, provider_model_id) DO UPDATE SET
                capabilities            = EXCLUDED.capabilities,
                context_window          = EXCLUDED.context_window,
                input_cost_per_million  = EXCLUDED.input_cost_per_million,
                output_cost_per_million = EXCLUDED.output_cost_per_million,
                supports_multimodal     = EXCLUDED.supports_multimodal,
                active                  = true,
                pricing_updated_at      = EXCLUDED.pricing_updated_at,
                updated_at              = now()
            """
        ).bindparams(
            catalog_id=QWEN_MODEL["id"],
            display_name=QWEN_MODEL["display_name"],
            provider_model_id=QWEN_MODEL["provider_model_id"],
            capabilities=json.dumps(QWEN_MODEL["capabilities"]),
            context_window=QWEN_MODEL["context_window"],
            input_cost=QWEN_MODEL["input_cost"],
            output_cost=QWEN_MODEL["output_cost"],
        )
    )

    _set_capabilities(CAPABILITY_FIXES)
    _refresh_pricing(OPENROUTER_REFRESH)

    for agent, provider, provider_model_id, rank in AGENT_MODELS:
        op.execute(
            sa.text(
                """
                UPDATE ai_model_catalog
                   SET agent_slug = :agent,
                       agent_preference_rank = :rank,
                       updated_at = now()
                 WHERE provider = :provider
                   AND provider_model_id = :provider_model_id
                """
            ).bindparams(
                agent=agent,
                rank=rank,
                provider=provider,
                provider_model_id=provider_model_id,
            )
        )

    # `openrouter-qwen3-coder` continua no catálogo servindo o AI Hub, mas sem
    # vínculo com o agente: o Qwen Code roda o 3.5 397B A17B.


def downgrade() -> None:
    op.drop_constraint(
        "ck_ai_model_agent_rank_positive", "ai_model_catalog", type_="check",
    )
    op.drop_constraint(
        "ck_ai_model_agent_rank_pair", "ai_model_catalog", type_="check",
    )
    op.drop_constraint(
        "uq_ai_model_agent_rank", "ai_model_catalog", type_="unique",
    )
    op.drop_column("ai_model_catalog", "agent_preference_rank")
    op.drop_column("ai_model_catalog", "agent_slug")

    _set_capabilities(CAPABILITY_ROLLBACK)
    _refresh_pricing(OPENROUTER_REFRESH_ROLLBACK)

    op.execute(
        sa.text(
            "DELETE FROM ai_model_catalog WHERE id IN ("
            "'anthropic-opus-5', 'anthropic-sonnet-5', "
            "'openrouter-qwen3-5-397b-a17b')"
        )
    )
