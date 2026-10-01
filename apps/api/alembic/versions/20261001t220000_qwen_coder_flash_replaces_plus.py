"""Qwen3 Coder Flash substitui o Qwen3 Coder Plus no agente qwen.

Revision ID: 20261001t220000
Revises: 20261001t140000
Create Date: 2026-10-01 22:00:00.000000

O qwen/qwen3-coder-plus sai da OpenRouter em 2026-10-09. A linha dele fica no
catálogo (servindo o histórico), só perde o vínculo com o agente; o Coder Flash
assume a posição 2 com o preço da OpenRouter conferido em 2026-10-01.
"""
from typing import Sequence, Union

import json

import sqlalchemy as sa
from alembic import op


revision: str = "20261001t220000"
down_revision: Union[str, Sequence[str], None] = "20261001t140000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CAPABILITIES = json.dumps(["code", "reasoning", "agentic", "repository_analysis", "review"])


def upgrade() -> None:
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = NULL, agent_preference_rank = NULL, updated_at = now()
         WHERE provider = 'openrouter' AND provider_model_id = 'qwen/qwen3-coder-plus'
    """))
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
            'openrouter-qwen3-coder-flash', 'Qwen3 Coder Flash', 'openrouter',
            'qwen/qwen3-coder-flash', 'economic', CAST(:capabilities AS jsonb), '[]', 1000000,
            0.195, 0.975, true, true, false, true, false, false, '[]', 'qwen', 2,
            '2026-10-01T00:00:00Z'
        )
        ON CONFLICT (provider, provider_model_id) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            context_window = EXCLUDED.context_window,
            input_cost_per_million = EXCLUDED.input_cost_per_million,
            output_cost_per_million = EXCLUDED.output_cost_per_million,
            active = true,
            agent_slug = EXCLUDED.agent_slug,
            agent_preference_rank = EXCLUDED.agent_preference_rank,
            pricing_updated_at = EXCLUDED.pricing_updated_at,
            updated_at = now()
    """).bindparams(capabilities=CAPABILITIES))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM ai_model_catalog WHERE id = 'openrouter-qwen3-coder-flash'"))
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = 'qwen', agent_preference_rank = 2, updated_at = now()
         WHERE provider = 'openrouter' AND provider_model_id = 'qwen/qwen3-coder-plus'
    """))
