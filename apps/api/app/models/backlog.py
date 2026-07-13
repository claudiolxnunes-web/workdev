from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class BacklogItem(Base):
    __tablename__ = "backlog"

    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    project_id = Column(UUID(as_uuid=True),
                        ForeignKey("projects.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    type = Column(String(20), nullable=False, server_default="feature")
    priority = Column(String(20), nullable=False, server_default="medium")
    status = Column(String(20), nullable=False, server_default="todo")
    owner = Column(String(100))
    effort = Column(Integer)
    sprint = Column(String(20))
    rank = Column(Integer)
    created_at = Column(DateTime, server_default=text("now()"))
    updated_at = Column(DateTime, server_default=text("now()"))
