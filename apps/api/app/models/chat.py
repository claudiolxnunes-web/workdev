from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base
# A definição canônica de autoridade (hierarquia, mapa de tools, rótulos) mora
# em app/services/autoridade.py. Aqui ficam só os nomes que o schema precisa.
from app.services.autoridade import (  # noqa: F401
    NIVEIS as AUTORIDADES,
    NIVEL_PADRAO as AUTORIDADE_PADRAO,
)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    title = Column(String(255), nullable=False)
    # Projeto ativo da conversa. SET NULL: apagar um projeto não apaga o
    # histórico do chat, só o vínculo — a conversa volta a ser global.
    project_id = Column(UUID(as_uuid=True),
                        ForeignKey("projects.id", ondelete="SET NULL"),
                        nullable=True)
    authority = Column(String(12), nullable=False,
                       server_default=AUTORIDADE_PADRAO)
    created_at = Column(DateTime, server_default=text("now()"))
    updated_at = Column(DateTime, server_default=text("now()"))

    __table_args__ = (
        Index("ix_chat_sessions_project", "project_id", "updated_at"),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    session_id = Column(UUID(as_uuid=True),
                        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
                        nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    # Lista (não objeto): um turno pode chamar várias tools. Cada item guarda
    # nome, argumentos e um resumo do retorno — o suficiente para auditar o
    # que a IA consultou ou alterou sem reexecutar nada.
    tool_calls = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    provider = Column(String(24))
    model = Column(String(64))
    created_at = Column(DateTime, server_default=text("now()"))

    __table_args__ = (
        Index("idx_chat_messages_session", "session_id", "created_at"),
    )
