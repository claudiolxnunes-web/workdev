from sqlalchemy import Column, String, Text, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class RFC(Base):
    __tablename__ = "rfcs"

    id = Column(UUID(as_uuid=True), primary_key=True,
                server_default=text("gen_random_uuid()"))
    project_id = Column(UUID(as_uuid=True),
                        ForeignKey("projects.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    title = Column(String(255), nullable=False)
    context = Column(Text, nullable=False)
    proposal = Column(Text, nullable=False)
    consequences = Column(Text)
    status = Column(String(20), nullable=False, server_default="draft")
    created_at = Column(DateTime, server_default=text("now()"))
    updated_at = Column(DateTime, server_default=text("now()"))
