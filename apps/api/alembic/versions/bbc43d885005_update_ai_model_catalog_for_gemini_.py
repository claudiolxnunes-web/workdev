"""update ai model catalog for gemini routing

Revision ID: bbc43d885005
Revises: f79645fadc70
Create Date: 2026-08-26 21:52:12.464752

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "bbc43d885005"
down_revision: Union[str, Sequence[str], None] = "f79645fadc70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


GEMINI_MODEL_IDS = (
    "gemini-1-5-flash-8b",
    "gemini-1-5-flash",
    "gemini-1-5-pro",
    "gemini-2-0-flash-lite",
    "gemini-2-0-flash",
    "gemini-2-5-flash",
    "gemini-2-5-pro",
    "gemini-3-5-flash",
)


def upgrade() -> None:
    """Add Gemini models used by WorkDev routing."""
    op.execute(
        sa.text(
            """
            INSERT INTO ai_model_catalog
              (
                id,
                display_name,
                provider,
                provider_model_id,
                category,
                capabilities,
                allowed_reasoning_efforts,
                context_window,
                input_cost_per_million,
                output_cost_per_million,
                supports_tools,
                supports_structured_output,
                supports_multimodal,
                active,
                is_free,
                requires_confirmation,
                allowed_fallbacks,
                pricing_updated_at
              )
            VALUES
              (
                'gemini-1-5-flash-8b',
                'Gemini 1.5 Flash-8B',
                'gemini',
                'gemini-1.5-flash-8b',
                'economic',
                '["conversation","summary","classification"]',
                '[]',
                NULL,
                0.0375,
                0.15,
                true,
                true,
                true,
                true,
                false,
                false,
                '["gemini-1-5-flash","gemini-2-0-flash-lite"]',
                '2026-08-26T00:00:00Z'
              ),
              (
                'gemini-1-5-flash',
                'Gemini 1.5 Flash',
                'gemini',
                'gemini-1.5-flash',
                'economic',
                '["conversation","summary","classification","multimodal"]',
                '[]',
                NULL,
                0.075,
                0.30,
                true,
                true,
                true,
                true,
                false,
                false,
                '["gemini-2-0-flash","gemini-1-5-flash-8b"]',
                '2026-08-26T00:00:00Z'
              ),
              (
                'gemini-1-5-pro',
                'Gemini 1.5 Pro',
                'gemini',
                'gemini-1.5-pro',
                'premium',
                '["reasoning","review","multimodal","large_context"]',
                '[]',
                NULL,
                1.25,
                5.00,
                true,
                true,
                true,
                true,
                false,
                true,
                '["gemini-2-5-flash","gemini-2-5-pro"]',
                '2026-08-26T00:00:00Z'
              ),
              (
                'gemini-2-0-flash-lite',
                'Gemini 2.0 Flash-Lite',
                'gemini',
                'gemini-2.0-flash-lite',
                'economic',
                '["conversation","summary","classification"]',
                '[]',
                NULL,
                0.075,
                0.30,
                true,
                true,
                true,
                true,
                false,
                false,
                '["gemini-2-0-flash","gemini-1-5-flash"]',
                '2026-08-26T00:00:00Z'
              ),
              (
                'gemini-2-0-flash',
                'Gemini 2.0 Flash',
                'gemini',
                'gemini-2.0-flash',
                'economic',
                '["conversation","code","summary","classification","multimodal"]',
                '[]',
                NULL,
                0.10,
                0.40,
                true,
                true,
                true,
                true,
                false,
                false,
                '["gemini-2-5-flash","gemini-2-0-flash-lite"]',
                '2026-08-26T00:00:00Z'
              ),
              (
                'gemini-2-5-flash',
                'Gemini 2.5 Flash',
                'gemini',
                'gemini-2.5-flash',
                'economic',
                '["reasoning","code","review","multimodal","agentic"]',
                '[]',
                NULL,
                0.15,
                0.60,
                true,
                true,
                true,
                true,
                false,
                false,
                '["gemini-2-0-flash","gemini-2-5-pro"]',
                '2026-08-26T00:00:00Z'
              ),
              (
                'gemini-2-5-pro',
                'Gemini 2.5 Pro',
                'gemini',
                'gemini-2.5-pro',
                'premium',
                '["deep_reasoning","code","review","architecture","multimodal","agentic"]',
                '[]',
                NULL,
                1.25,
                10.00,
                true,
                true,
                true,
                true,
                false,
                true,
                '["gemini-2-5-flash","gemini-1-5-pro"]',
                '2026-08-26T00:00:00Z'
              ),
              (
                'gemini-3-5-flash',
                'Gemini 3.5 Flash',
                'gemini',
                'gemini-3.5-flash',
                'premium',
                '["deep_reasoning","code","review","multimodal","agentic"]',
                '[]',
                NULL,
                2.70,
                16.20,
                true,
                true,
                true,
                true,
                false,
                true,
                '["gemini-2-5-pro","gemini-2-5-flash"]',
                '2026-08-26T00:00:00Z'
              )
            ON CONFLICT (id) DO UPDATE SET
              display_name = EXCLUDED.display_name,
              provider = EXCLUDED.provider,
              provider_model_id = EXCLUDED.provider_model_id,
              category = EXCLUDED.category,
              capabilities = EXCLUDED.capabilities,
              allowed_reasoning_efforts = EXCLUDED.allowed_reasoning_efforts,
              context_window = EXCLUDED.context_window,
              input_cost_per_million = EXCLUDED.input_cost_per_million,
              output_cost_per_million = EXCLUDED.output_cost_per_million,
              supports_tools = EXCLUDED.supports_tools,
              supports_structured_output = EXCLUDED.supports_structured_output,
              supports_multimodal = EXCLUDED.supports_multimodal,
              active = EXCLUDED.active,
              is_free = EXCLUDED.is_free,
              requires_confirmation = EXCLUDED.requires_confirmation,
              allowed_fallbacks = EXCLUDED.allowed_fallbacks,
              pricing_updated_at = EXCLUDED.pricing_updated_at,
              updated_at = now()
            """
        )
    )


def downgrade() -> None:
    """Remove Gemini models introduced by this migration."""
    op.execute(
        sa.text(
            """
            DELETE FROM ai_model_catalog
            WHERE id IN (
              'gemini-1-5-flash-8b',
              'gemini-1-5-flash',
              'gemini-1-5-pro',
              'gemini-2-0-flash-lite',
              'gemini-2-0-flash',
              'gemini-2-5-flash',
              'gemini-2-5-pro',
              'gemini-3-5-flash'
            )
            """
        )
    )
