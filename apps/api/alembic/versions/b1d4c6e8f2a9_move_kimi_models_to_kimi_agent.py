"""Move Kimi K2.7/K2.6 from generic OpenRouter agent to Kimi agent.

Revision ID: b1d4c6e8f2a9
Revises: a2f6d8c91b04
Create Date: 2026-09-30
"""

import sqlalchemy as sa
from alembic import op


revision = "b1d4c6e8f2a9"
down_revision = "a2f6d8c91b04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Kimi K2.7 e K2.6 pertencem ao agente Kimi, não ao agente OpenRouter genérico.
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = 'kimi',
               agent_preference_rank = CASE provider_model_id
                   WHEN 'moonshotai/kimi-k2.7-code' THEN 2
                   WHEN 'moonshotai/kimi-k2.6' THEN 3
               END,
               updated_at = now()
         WHERE provider = 'openrouter'
           AND provider_model_id IN ('moonshotai/kimi-k2.7-code', 'moonshotai/kimi-k2.6')
    """))

    # Reordena os modelos restantes do agente OpenRouter genérico (qwen).
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_preference_rank = CASE provider_model_id
                   WHEN 'qwen/qwen3.5-397b-a17b' THEN 1
                   WHEN 'deepseek/deepseek-v4-flash' THEN 2
                   WHEN 'x-ai/grok-4.7' THEN 3
               END,
               updated_at = now()
         WHERE provider = 'openrouter'
           AND agent_slug = 'qwen'
    """))

    # Garante que kimi-k3 continue rank 1 no agente Kimi.
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_preference_rank = 1,
               updated_at = now()
         WHERE provider = 'openrouter'
           AND provider_model_id = 'moonshotai/kimi-k3'
           AND agent_slug = 'kimi'
    """))


def downgrade() -> None:
    # Volta K2.7/K2.6 para o agente OpenRouter genérico.
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = 'qwen',
               agent_preference_rank = CASE provider_model_id
                   WHEN 'moonshotai/kimi-k2.7-code' THEN 3
                   WHEN 'moonshotai/kimi-k2.6' THEN 4
               END,
               updated_at = now()
         WHERE provider = 'openrouter'
           AND provider_model_id IN ('moonshotai/kimi-k2.7-code', 'moonshotai/kimi-k2.6')
    """))

    # Restaura ranks anteriores do agente qwen.
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_preference_rank = CASE provider_model_id
                   WHEN 'qwen/qwen3.5-397b-a17b' THEN 1
                   WHEN 'deepseek/deepseek-v4-flash' THEN 2
                   WHEN 'moonshotai/kimi-k2.7-code' THEN 3
                   WHEN 'moonshotai/kimi-k2.6' THEN 4
                   WHEN 'x-ai/grok-4.7' THEN 5
               END,
               updated_at = now()
         WHERE provider = 'openrouter'
           AND agent_slug = 'qwen'
    """))
