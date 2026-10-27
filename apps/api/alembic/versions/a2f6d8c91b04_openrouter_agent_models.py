"""Configure the generic OpenRouter agent model catalog.

Revision ID: a2f6d8c91b04
Revises: 9f2b4d6a8c10
Create Date: 2026-09-28
"""

import json

import sqlalchemy as sa
from alembic import op


revision = "a2f6d8c91b04"
down_revision = "9f2b4d6a8c10"
branch_labels = None
depends_on = None


MODELS = (
    # id, display name, provider model id, rank, input/output USD per 1M, context
    ("openrouter-qwen3-5-397b-a17b", "Qwen Coder (Qwen 3.5)",
     "qwen/qwen3.5-397b-a17b", 1, 0.39, 2.34, 262144),
    ("openrouter-deepseek-v4-flash", "DeepSeek V4 Flash",
     "deepseek/deepseek-v4-flash", 2, 0.0679, 0.168, 1048576),
    ("openrouter-kimi-k2-7-code", "Kimi K2.7 Code",
     "moonshotai/kimi-k2.7-code", 3, 0.68, 3.40, 262144),
    ("openrouter-kimi-k2-6", "Kimi K2.6",
     "moonshotai/kimi-k2.6", 4, 0.58, 3.40, 262144),
    ("openrouter-grok-4-7", "Grok 4.7",
     "x-ai/grok-4.7", 5, 1.60, 4.80, 500000),
)

CAPABILITIES = json.dumps([
    "code", "reasoning", "agentic", "repository_analysis", "review",
])


def upgrade() -> None:
    # Libera os ranks antes de mover K2.7 do Kimi para o agente OpenRouter.
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = NULL, agent_preference_rank = NULL, updated_at = now()
         WHERE agent_slug IN ('qwen', 'kimi')
    """))

    for catalog_id, display_name, model_id, rank, input_cost, output_cost, context in MODELS:
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
                :catalog_id, :display_name, 'openrouter', :model_id, 'economic',
                CAST(:capabilities AS jsonb), '[]', :context,
                :input_cost, :output_cost, true, true, true, true, false,
                false, '[]', 'qwen', :rank, '2026-09-28T00:00:00Z'
            )
            ON CONFLICT (provider, provider_model_id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                capabilities = EXCLUDED.capabilities,
                context_window = EXCLUDED.context_window,
                input_cost_per_million = EXCLUDED.input_cost_per_million,
                output_cost_per_million = EXCLUDED.output_cost_per_million,
                supports_tools = true,
                supports_structured_output = true,
                supports_multimodal = true,
                active = true,
                agent_slug = 'qwen',
                agent_preference_rank = EXCLUDED.agent_preference_rank,
                pricing_updated_at = EXCLUDED.pricing_updated_at,
                updated_at = now()
        """).bindparams(
            catalog_id=catalog_id, display_name=display_name, model_id=model_id,
            rank=rank, input_cost=input_cost, output_cost=output_cost,
            context=context, capabilities=CAPABILITIES,
        ))

    # Kimi Code continua existindo, agora exclusivamente no Kimi 3.
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = 'kimi', agent_preference_rank = 1, updated_at = now()
         WHERE provider = 'openrouter'
           AND provider_model_id = 'moonshotai/kimi-k3'
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = NULL, agent_preference_rank = NULL, updated_at = now()
         WHERE agent_slug IN ('qwen', 'kimi')
    """))
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = 'qwen', agent_preference_rank = 1, updated_at = now()
         WHERE provider = 'openrouter'
           AND provider_model_id = 'qwen/qwen3.5-397b-a17b'
    """))
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = 'kimi',
               agent_preference_rank = CASE provider_model_id
                   WHEN 'moonshotai/kimi-k3' THEN 1 ELSE 2 END,
               updated_at = now()
         WHERE provider = 'openrouter'
           AND provider_model_id IN ('moonshotai/kimi-k3', 'moonshotai/kimi-k2.7-code')
    """))
    op.execute(sa.text("""
        DELETE FROM ai_model_catalog
         WHERE id IN ('openrouter-deepseek-v4-flash',
                      'openrouter-kimi-k2-6', 'openrouter-grok-4-7')
    """))
