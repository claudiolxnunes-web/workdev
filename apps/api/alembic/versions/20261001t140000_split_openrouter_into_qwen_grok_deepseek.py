"""Split generic OpenRouter agent into qwen, grok and deepseek.

Revision ID: 20261001t140000
Revises: d0bacf258e0d
Create Date: 2026-10-01 14:00:00.000000

Os três agentes rodam a CLI qwen contra a OpenRouter; muda só o vínculo do
catálogo e a identidade gravada nas runs.

- Catálogo: modelos reais da OpenRouter, preços conferidos em 2026-10-01, na
  mesma ordem de cli_agent_models.MODELS (rank 1 = padrão do agente).
- Runs com agent 'openrouter' vão para o agente do prefixo do modelo gravado
  (x-ai/ -> grok, deepseek/ -> deepseek, demais ou sem modelo -> qwen).
- reviewer_agent 'openrouter' vira 'qwen' em TODAS as runs, não só nas que
  tinham executor openrouter (a cdf620c7a45a deixou esse ponto cego).
- reviewer_agent 'qwen' anterior à cdf620c7a45a fica como está: 'qwen' volta a
  ser um agente válido, e era a mesma CLI qwen.
- updated_at das runs não é tocado: é renomeação de identidade, não trabalho.
"""
from typing import Sequence, Union

import json

import sqlalchemy as sa
from alembic import op


revision: str = "20261001t140000"
down_revision: Union[str, Sequence[str], None] = "d0bacf258e0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MODELS = (
    # agent, id, display name, provider model id, rank, input/output USD por 1M, contexto
    ("qwen", "openrouter-qwen3-5-397b-a17b", "Qwen Coder (Qwen 3.5)",
     "qwen/qwen3.5-397b-a17b", 1, 0.55, 3.50, 262144),
    ("qwen", "openrouter-qwen3-coder-plus", "Qwen3 Coder Plus",
     "qwen/qwen3-coder-plus", 2, 0.65, 3.25, 1000000),
    ("qwen", "openrouter-qwen3-coder-next", "Qwen3 Coder Next",
     "qwen/qwen3-coder-next", 3, 0.12, 0.80, 262144),
    ("grok", "openrouter-grok-4-7", "Grok 4.7",
     "x-ai/grok-4.7", 1, 2.00, 6.00, 500000),
    ("grok", "openrouter-grok-4-3", "Grok 4.3",
     "x-ai/grok-4.3", 2, 1.25, 2.50, 1000000),
    ("grok", "openrouter-grok-build-0-1", "Grok Build 0.1",
     "x-ai/grok-build-0.1", 3, 1.00, 2.00, 256000),
    ("deepseek", "openrouter-deepseek-v4-flash", "DeepSeek V4 Flash",
     "deepseek/deepseek-v4-flash", 1, 0.0419, 0.0837, 1048576),
    ("deepseek", "openrouter-deepseek-v4-1-flash", "DeepSeek V4.1 Flash",
     "deepseek/deepseek-v4.1-flash", 2, 0.03, 0.50, 1048576),
    ("deepseek", "openrouter-deepseek-v4-pro-0813", "DeepSeek V4 Pro 0813",
     "deepseek/deepseek-v4-pro-0813", 3, 0.66, 1.98, 1048576),
)

# Linhas que esta revisão cria; as demais já existiam e só têm o vínculo trocado.
CREATED_IDS = (
    "openrouter-qwen3-coder-plus",
    "openrouter-qwen3-coder-next",
    "openrouter-grok-4-3",
    "openrouter-grok-build-0-1",
    "openrouter-deepseek-v4-1-flash",
    "openrouter-deepseek-v4-pro-0813",
)

# Estado da a2f6d8c91b04/d0bacf258e0d, restaurado no downgrade.
PREVIOUS = (
    # provider model id, rank no agente openrouter, input, output
    ("qwen/qwen3.5-397b-a17b", 1, 0.39, 2.34),
    ("deepseek/deepseek-v4-flash", 2, 0.0679, 0.168),
    ("x-ai/grok-4.7", 3, 1.60, 4.80),
)

# Tier pedido pelo operador: Grok 4.7 premium, 4.3 médio, Build 0.1 barato.
PREMIUM = {"x-ai/grok-4.7": "premium"}

CAPABILITIES = json.dumps([
    "code", "reasoning", "agentic", "repository_analysis", "review",
])

AGENTS = ("qwen", "grok", "deepseek")


def upgrade() -> None:
    # Libera os ranks antes de reatribuir (uq_ai_model_agent_rank).
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = NULL, agent_preference_rank = NULL, updated_at = now()
         WHERE agent_slug IN ('openrouter', 'qwen', 'grok', 'deepseek')
    """))

    for agent, catalog_id, display_name, model_id, rank, input_cost, output_cost, context in MODELS:
        category = PREMIUM.get(model_id, "economic")
        op.execute(sa.text("""
            INSERT INTO ai_model_catalog (
                id, display_name, provider, provider_model_id, category,
                capabilities, allowed_reasoning_efforts, context_window,
                input_cost_per_million, output_cost_per_million,
                supports_tools, supports_structured_output,
                supports_multimodal, active, is_free, requires_confirmation,
                allowed_fallbacks, agent_slug, agent_preference_rank,
                pricing_updated_at
            ) VALUES (
                :catalog_id, :display_name, 'openrouter', :model_id, :category,
                CAST(:capabilities AS jsonb), '[]', :context,
                :input_cost, :output_cost, true, true, false, true, false,
                false, '[]', :agent, :rank, '2026-10-01T00:00:00Z'
            )
            ON CONFLICT (provider, provider_model_id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                category = EXCLUDED.category,
                context_window = EXCLUDED.context_window,
                input_cost_per_million = EXCLUDED.input_cost_per_million,
                output_cost_per_million = EXCLUDED.output_cost_per_million,
                active = true,
                agent_slug = EXCLUDED.agent_slug,
                agent_preference_rank = EXCLUDED.agent_preference_rank,
                pricing_updated_at = EXCLUDED.pricing_updated_at,
                updated_at = now()
        """).bindparams(
            catalog_id=catalog_id, display_name=display_name, model_id=model_id,
            rank=rank, input_cost=input_cost, output_cost=output_cost,
            context=context, capabilities=CAPABILITIES, agent=agent,
            category=category,
        ))

    op.execute(sa.text("""
        UPDATE agent_runs
           SET agent = CASE
                   WHEN model LIKE 'x-ai/%' THEN 'grok'
                   WHEN model LIKE 'deepseek/%' THEN 'deepseek'
                   ELSE 'qwen'
               END
         WHERE agent = 'openrouter'
    """))
    op.execute(sa.text("""
        UPDATE agent_runs SET reviewer_agent = 'qwen' WHERE reviewer_agent = 'openrouter'
    """))
    op.execute(sa.text("""
        UPDATE agent_run_reviews
           SET executor_agent = CASE WHEN executor_agent = 'openrouter' THEN 'qwen' ELSE executor_agent END,
               reviewer_agent = CASE WHEN reviewer_agent = 'openrouter' THEN 'qwen' ELSE reviewer_agent END
         WHERE executor_agent = 'openrouter' OR reviewer_agent = 'openrouter'
    """))


def downgrade() -> None:
    # Volta a um único agente 'openrouter'. Perde a distinção qwen/grok/deepseek
    # e também converte reviewer 'qwen' anterior à cdf620c7a45a, como ela fazia.
    op.execute(sa.text("""
        UPDATE agent_runs SET agent = 'openrouter' WHERE agent IN ('qwen', 'grok', 'deepseek')
    """))
    op.execute(sa.text("""
        UPDATE agent_runs SET reviewer_agent = 'openrouter'
         WHERE reviewer_agent IN ('qwen', 'grok', 'deepseek')
    """))
    op.execute(sa.text("""
        UPDATE agent_run_reviews
           SET executor_agent = CASE WHEN executor_agent IN ('qwen', 'grok', 'deepseek')
                                     THEN 'openrouter' ELSE executor_agent END,
               reviewer_agent = CASE WHEN reviewer_agent IN ('qwen', 'grok', 'deepseek')
                                     THEN 'openrouter' ELSE reviewer_agent END
         WHERE executor_agent IN ('qwen', 'grok', 'deepseek')
            OR reviewer_agent IN ('qwen', 'grok', 'deepseek')
    """))

    op.execute(
        sa.text("DELETE FROM ai_model_catalog WHERE id IN :ids")
        .bindparams(sa.bindparam("ids", value=list(CREATED_IDS), expanding=True))
    )
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = NULL, agent_preference_rank = NULL, updated_at = now()
         WHERE agent_slug IN ('qwen', 'grok', 'deepseek')
    """))
    for model_id, rank, input_cost, output_cost in PREVIOUS:
        op.execute(sa.text("""
            UPDATE ai_model_catalog
               SET agent_slug = 'openrouter', agent_preference_rank = :rank,
                   category = 'economic',
                   input_cost_per_million = :input_cost,
                   output_cost_per_million = :output_cost,
                   updated_at = now()
             WHERE provider = 'openrouter' AND provider_model_id = :model_id
        """).bindparams(model_id=model_id, rank=rank,
                        input_cost=input_cost, output_cost=output_cost))
