from sqlalchemy import (Column, String, Text, DateTime, Integer,
                        ForeignKey, text, Index)
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class BacklogSubtask(Base):
    __tablename__ = "backlog_subtasks"

    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    backlog_id = Column(UUID(as_uuid=True),
                        ForeignKey("backlog.id", ondelete="CASCADE"),
                        nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text)
    status = Column(String(20), nullable=False, server_default="todo")
    execution_order = Column(Integer, nullable=False, server_default=text("0"))
    assigned_agent = Column(String(50))
    result = Column(Text)
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("idx_backlog_subtasks_backlog_id", "backlog_id"),
        Index("idx_backlog_subtasks_status", "status"),
        Index("idx_backlog_subtasks_agent", "assigned_agent"),
    )
