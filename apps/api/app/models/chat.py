from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    title = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=text("now()"))
    updated_at = Column(DateTime, server_default=text("now()"))


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    session_id = Column(UUID(as_uuid=True),
                        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
                        nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=text("now()"))

    __table_args__ = (
        Index("idx_chat_messages_session", "session_id", "created_at"),
    )
