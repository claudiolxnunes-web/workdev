"""Modelos do Chat livre do AI Hub.

Isolamento é a regra: estas tabelas não têm FK para backlog, execution_plans,
knowledge ou adrs. Uma conversa de chat livre nunca escreve no sistema — o
endpoint correspondente chama o modelo sem enviar nenhuma tool.

`chat_messages` já existia (chat do AI Hub com tools, ligado a chat_sessions),
por isso as mensagens daqui usam o nome `chat_free_messages`.
"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, text
from sqlalchemy import Boolean, Integer, Numeric
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class ChatConversation(Base):
    __tablename__ = "chat_conversations"
    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    title = Column(String(255), nullable=False)
    # Título nasce da primeira mensagem; depois que o usuário renomeia, a
    # primeira mensagem nunca mais sobrescreve.
    title_locked = Column(Boolean, nullable=False, server_default=text("false"))
    input_tokens = Column(Integer, nullable=False, server_default=text("0"))
    output_tokens = Column(Integer, nullable=False, server_default=text("0"))
    cost_usd = Column(Numeric(12, 8), nullable=False, server_default=text("0"))
    created_at = Column(DateTime, server_default=text("now()"))
    updated_at = Column(DateTime, server_default=text("now()"))

    __table_args__ = (
        Index("ix_chat_conversations_updated", "updated_at"),
    )


class ChatFreeMessage(Base):
    __tablename__ = "chat_free_messages"
    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    conversation_id = Column(UUID(as_uuid=True),
                             ForeignKey("chat_conversations.id",
                                        ondelete="CASCADE"),
                             nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    provider = Column(String(24))
    model = Column(String(128))
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    cost_usd = Column(Numeric(12, 8))
    created_at = Column(DateTime, server_default=text("now()"))

    __table_args__ = (
        Index("ix_chat_free_messages_conversation",
              "conversation_id", "created_at"),
    )
