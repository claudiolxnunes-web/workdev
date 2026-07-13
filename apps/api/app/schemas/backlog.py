from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class BacklogCreate(BaseModel):
    project_id: UUID
    title: str
    description: Optional[str] = None
    type: str = "feature"
    priority: str = "medium"
    status: str = "todo"
    owner: Optional[str] = None
    effort: Optional[int] = None
    sprint: Optional[str] = None
    rank: Optional[int] = None


class BacklogUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    owner: Optional[str] = None
    effort: Optional[int] = None
    sprint: Optional[str] = None
    rank: Optional[int] = None


class BacklogOut(BacklogCreate):
    id: UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
