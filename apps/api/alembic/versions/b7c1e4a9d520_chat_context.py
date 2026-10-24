"""chat context: projeto ativo, autoridade e auditoria de tool calls

Revision ID: b7c1e4a9d520
Revises: 2c53d77a9f4b
Create Date: 2026-08-16

Fase E1.1 do WorkDev Conversational Core.

Duas coisas acontecem aqui, nesta ordem:

1. `chat_sessions` e `chat_messages` nunca tiveram migration de criação — foram
   criadas à mão fora do Alembic. O `CREATE TABLE IF NOT EXISTS` abaixo não faz
   nada no banco de produção (as tabelas já existem, com 37 sessões e 801
   mensagens) e passa a criá-las corretamente em qualquer banco novo. Sem isso,
   um `alembic upgrade head` do zero produz um schema sem o AI Hub.

2. As colunas de contexto. Tudo aditivo: nullable ou com server_default, sem
   reescrita de tabela e sem downtime.

Escrita à mão de propósito. O autogenerate desta base já tentou dropar
`chat_sessions`/`chat_messages` uma vez (ver aaa20863cb97) e as colunas abaixo
precisam ser idempotentes para conviver com o banco criado manualmente.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b7c1e4a9d520"
down_revision: Union[str, Sequence[str], None] = "2c53d77a9f4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. registra no Alembic o schema que hoje só existe porque foi criado à mão
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            title      varchar(255) NOT NULL,
            created_at timestamp DEFAULT now(),
            updated_at timestamp DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id uuid NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            role       varchar(20) NOT NULL,
            content    text NOT NULL,
            created_at timestamp DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session
            ON chat_messages (session_id, created_at)
        """
    )

    # 2. contexto ativo da conversa
    op.execute(
        """
        ALTER TABLE chat_sessions
            ADD COLUMN IF NOT EXISTS project_id uuid
                REFERENCES projects(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS authority varchar(12) NOT NULL DEFAULT 'plan'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chat_sessions_project
            ON chat_sessions (project_id, updated_at)
        """
    )

    # 3. auditoria por mensagem
    op.execute(
        """
        ALTER TABLE chat_messages
            ADD COLUMN IF NOT EXISTS tool_calls jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS provider varchar(24),
            ADD COLUMN IF NOT EXISTS model varchar(64)
        """
    )


def downgrade() -> None:
    # Só desfaz o que a etapa 2 e 3 acrescentaram. As tabelas em si não são
    # dropadas: elas são anteriores a esta migration e carregam o histórico
    # real do AI Hub.
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_project")
    op.execute(
        """
        ALTER TABLE chat_messages
            DROP COLUMN IF EXISTS tool_calls,
            DROP COLUMN IF EXISTS provider,
            DROP COLUMN IF EXISTS model
        """
    )
    op.execute(
        """
        ALTER TABLE chat_sessions
            DROP COLUMN IF EXISTS project_id,
            DROP COLUMN IF EXISTS authority
        """
    )
