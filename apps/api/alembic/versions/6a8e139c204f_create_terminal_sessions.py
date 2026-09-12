"""Create persistent per-run terminal identities.

Revision ID: 6a8e139c204f
Revises: d4a1c7e39b52
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '6a8e139c204f'
down_revision = 'd4a1c7e39b52'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('terminal_sessions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True), sa.ForeignKey('agent_runs.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('state', sa.String(16), nullable=False),
        sa.Column('supervisor_pid', sa.Integer()),
        sa.Column('pid', sa.Integer()),
        sa.Column('process_identity', sa.String(100)),
        sa.Column('pty_path', sa.String(100)),
        sa.Column('socket_path', sa.Text(), nullable=False),
        sa.Column('cwd', sa.Text(), nullable=False),
        sa.Column('exit_code', sa.Integer()),
        sa.Column('error', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('closed_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('run_id', name='uq_terminal_sessions_run_id'),
        sa.CheckConstraint("state IN ('STARTING','RUNNING','STOPPING','CLOSED','ERROR')", name='ck_terminal_session_state'))


def downgrade():
    op.drop_table('terminal_sessions')
