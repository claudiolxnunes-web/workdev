from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class KnowledgeCreate(BaseModel):
    title: str
    content: str
    category: str = "licao"
    tags: Optional[str] = None
    project_id: Optional[UUID] = None
    backlog_id: Optional[UUID] = None


class KnowledgeOut(KnowledgeCreate):
    id: UUID
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
