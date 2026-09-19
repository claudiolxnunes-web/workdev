"""chat livre: conversas sem tools, independentes de planos/tasks

Revision ID: f3e1c9a42b77
Revises: r3v1ewcycle001
Create Date: 2026-09-18

Cria as tabelas do Chat livre do AI Hub. São propositalmente isoladas:
nenhuma FK aponta para backlog, execution_plans, knowledge ou adrs — o que
garante, no nível do banco, que uma sessão de chat livre nunca escreve no
sistema. `chat_messages` já existia (chat do AI Hub com tools), então as
mensagens do chat livre usam o nome `chat_free_messages`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f3e1c9a42b77'
down_revision: Union[str, Sequence[str], None] = 'r3v1ewcycle001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_conversations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('title_locked', sa.Boolean(), nullable=False,
                  server_default=sa.text('false')),
        sa.Column('input_tokens', sa.Integer(), nullable=False,
                  server_default=sa.text('0')),
        sa.Column('output_tokens', sa.Integer(), nullable=False,
                  server_default=sa.text('0')),
        sa.Column('cost_usd', sa.Numeric(12, 8), nullable=False,
                  server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    op.create_index('ix_chat_conversations_updated',
                    'chat_conversations', ['updated_at'])

    op.create_table(
        'chat_free_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('chat_conversations.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('provider', sa.String(24)),
        sa.Column('model', sa.String(128)),
        sa.Column('input_tokens', sa.Integer()),
        sa.Column('output_tokens', sa.Integer()),
        sa.Column('cost_usd', sa.Numeric(12, 8)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
    )
    op.create_index('ix_chat_free_messages_conversation',
                    'chat_free_messages', ['conversation_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_chat_free_messages_conversation',
                  table_name='chat_free_messages')
    op.drop_table('chat_free_messages')
    op.drop_index('ix_chat_conversations_updated',
                  table_name='chat_conversations')
    op.drop_table('chat_conversations')
