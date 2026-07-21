from sqlalchemy import Column, String, Text, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class KnowledgeEntry(Base):
    __tablename__ = "knowledge"

    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    project_id = Column(UUID(as_uuid=True),
                        ForeignKey("projects.id", ondelete="SET NULL"),
                        nullable=True, index=True)
    backlog_id = Column(UUID(as_uuid=True),
                        ForeignKey("backlog.id", ondelete="SET NULL"),
                        nullable=True, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    category = Column(String(20), nullable=False, server_default="licao")
    tags = Column(String(255))
    created_at = Column(DateTime, server_default=text("now()"))
