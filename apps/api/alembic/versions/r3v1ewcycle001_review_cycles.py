"""review_cycles: métricas e auditoria do ciclo de revisão por risco

Revision ID: r3v1ewcycle001
Revises: 6a8e139c204f
Create Date: 2026-09-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'r3v1ewcycle001'
down_revision: Union[str, Sequence[str], None] = '6a8e139c204f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'review_cycles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('run_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('agent_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('decision', sa.String(24), nullable=False),
        sa.Column('tier', sa.String(16), nullable=False, server_default='none'),
        sa.Column('task_risk', sa.String(16), nullable=False),
        sa.Column('agent_trust', sa.String(16), nullable=False),
        sa.Column('gate_result', sa.String(16), nullable=False),
        sa.Column('sensitive', postgresql.JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column('justification', sa.Text(), nullable=False),
        sa.Column('diff_files', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('diff_lines', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('context_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tokens_estimate', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reviewer_agent', sa.String(32)),
        sa.Column('verdict', sa.String(16)),
        sa.Column('escalated', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('duration_ms', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('closed_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_review_cycles_run_id', 'review_cycles', ['run_id'])


def downgrade() -> None:
    op.drop_index('ix_review_cycles_run_id', table_name='review_cycles')
    op.drop_table('review_cycles')
