"""rename qwen agent slug to openrouter

Revision ID: cdf620c7a45a
Revises: b1d4c6e8f2a9
Create Date: 2026-10-01 08:31:25.691980

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cdf620c7a45a'
down_revision: Union[str, Sequence[str], None] = 'b1d4c6e8f2a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = 'openrouter',
               updated_at = now()
         WHERE agent_slug = 'qwen'
    """))

    op.execute(sa.text("""
        UPDATE agent_runs
           SET agent = 'openrouter',
               reviewer_agent = CASE WHEN reviewer_agent = 'qwen' THEN 'openrouter' ELSE reviewer_agent END,
               updated_at = now()
         WHERE agent = 'qwen'
    """))

    op.execute(sa.text("""
        UPDATE agent_run_reviews
           SET executor_agent = CASE WHEN executor_agent = 'qwen' THEN 'openrouter' ELSE executor_agent END,
               reviewer_agent = CASE WHEN reviewer_agent = 'qwen' THEN 'openrouter' ELSE reviewer_agent END
         WHERE executor_agent = 'qwen' OR reviewer_agent = 'qwen'
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        UPDATE ai_model_catalog
           SET agent_slug = 'qwen',
               updated_at = now()
         WHERE agent_slug = 'openrouter'
    """))

    op.execute(sa.text("""
        UPDATE agent_runs
           SET agent = 'qwen',
               reviewer_agent = CASE WHEN reviewer_agent = 'openrouter' THEN 'qwen' ELSE reviewer_agent END,
               updated_at = now()
         WHERE agent = 'openrouter'
    """))

    op.execute(sa.text("""
        UPDATE agent_run_reviews
           SET executor_agent = CASE WHEN executor_agent = 'openrouter' THEN 'qwen' ELSE executor_agent END,
               reviewer_agent = CASE WHEN reviewer_agent = 'openrouter' THEN 'qwen' ELSE reviewer_agent END
         WHERE executor_agent = 'openrouter' OR reviewer_agent = 'openrouter'
    """))

