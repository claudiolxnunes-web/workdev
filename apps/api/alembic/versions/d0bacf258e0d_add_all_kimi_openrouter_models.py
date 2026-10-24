"""Adiciona todos os modelos Kimi disponíveis na OpenRouter ao agente Kimi.

Revision ID: d0bacf258e0d
Revises: cdf620c7a45a
Create Date: 2026-10-01 08:51:12.268170
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0bacf258e0d"
down_revision: Union[str, Sequence[str], None] = "cdf620c7a45a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (catalog_id, display_name, provider_model_id, rank, category,
#  input_cost, output_cost, context_window, requires_confirmation, capabilities)
KIMI_MODELS = (
    ("openrouter-kimi-k3", "Kimi K3", "moonshotai/kimi-k3",
     1, "premium", 0.677, 10.00, 1048576, True,
     '["multimodal", "agentic", "code", "repository_analysis", "reasoning", "review", "large_context"]'),
    ("openrouter-kimi-k3-batch", "Kimi K3 (Batch)", "moonshotai/kimi-k3:batch",
     2, "premium", 2.28, 11.40, 1048576, True,
     '["multimodal", "agentic", "code", "repository_analysis", "reasoning", "review", "large_context"]'),
    ("openrouter-kimi-k2-7-code", "Kimi K2.7 Code", "moonshotai/kimi-k2.7-code",
     3, "economic", 0.6712, 3.35, 262144, False,
     '["code", "repository_analysis", "reasoning", "multimodal"]'),
    ("openrouter-kimi-k2-6", "Kimi K2.6", "moonshotai/kimi-k2.6",
     4, "economic", 0.65, 3.41, 262144, False,
     '["code", "repository_analysis", "reasoning", "multimodal"]'),
    ("openrouter-kimi-k2-5", "Kimi K2.5", "moonshotai/kimi-k2.5",
     5, "economic", 0.45, 2.25, 262144, False,
     '["code", "repository_analysis", "reasoning", "multimodal"]'),
    ("openrouter-kimi-k2-thinking", "Kimi K2 Thinking", "moonshotai/kimi-k2-thinking",
     6, "economic", 0.60, 2.50, 262144, False,
     '["code", "repository_analysis", "reasoning", "multimodal"]'),
    ("openrouter-kimi-k2-0905", "Kimi K2 0905", "moonshotai/kimi-k2-0905",
     7, "economic", 0.60, 2.50, 262144, False,
     '["code", "repository_analysis", "reasoning", "multimodal"]'),
    ("openrouter-kimi-k2", "Kimi K2", "moonshotai/kimi-k2",
     8, "economic", 0.57, 2.30, 131072, False,
     '["code", "repository_analysis", "reasoning", "multimodal"]'),
)


def upgrade() -> None:
    # Libera os ranks atuais do agente Kimi antes de redefinir a ordem
    # com todos os modelos do catálogo OpenRouter.
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = NULL,
               agent_preference_rank = NULL,
               updated_at = now()
         WHERE provider = 'openrouter'
           AND provider_model_id LIKE 'moonshotai/kimi-%'
    """))

    for (
        catalog_id, display_name, provider_model_id, rank, category,
        input_cost, output_cost, context_window, requires_confirmation,
        capabilities,
    ) in KIMI_MODELS:
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
                    agent_slug, agent_preference_rank,
                    pricing_updated_at
                ) VALUES (
                    :catalog_id, :display_name, 'openrouter', :provider_model_id,
                    :category, CAST(:capabilities AS jsonb), '[]', :context_window,
                    :input_cost, :output_cost, true, true, true, true, false,
                    :requires_confirmation, '[]', 'kimi', :rank,
                    '2026-10-01T00:00:00Z'
                )
                ON CONFLICT (provider, provider_model_id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    category = EXCLUDED.category,
                    capabilities = EXCLUDED.capabilities,
                    context_window = EXCLUDED.context_window,
                    input_cost_per_million = EXCLUDED.input_cost_per_million,
                    output_cost_per_million = EXCLUDED.output_cost_per_million,
                    supports_tools = true,
                    supports_structured_output = true,
                    supports_multimodal = true,
                    active = true,
                    requires_confirmation = EXCLUDED.requires_confirmation,
                    agent_slug = 'kimi',
                    agent_preference_rank = EXCLUDED.agent_preference_rank,
                    pricing_updated_at = EXCLUDED.pricing_updated_at,
                    updated_at = now()
                """
            ).bindparams(
                catalog_id=catalog_id,
                display_name=display_name,
                provider_model_id=provider_model_id,
                rank=rank,
                category=category,
                input_cost=input_cost,
                output_cost=output_cost,
                context_window=context_window,
                requires_confirmation=requires_confirmation,
                capabilities=capabilities,
            )
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM ai_model_catalog
             WHERE provider_model_id IN (
                 'moonshotai/kimi-k3:batch',
                 'moonshotai/kimi-k2.5',
                 'moonshotai/kimi-k2-thinking',
                 'moonshotai/kimi-k2-0905',
                 'moonshotai/kimi-k2'
             )
            """
        )
    )
