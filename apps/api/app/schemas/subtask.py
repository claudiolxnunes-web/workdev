from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional


class SubtaskCreate(BaseModel):
    backlog_id: UUID
    title: str
    description: Optional[str] = None
    status: str = "todo"
    execution_order: int = 0
    assigned_agent: Optional[str] = None


class SubtaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    execution_order: Optional[int] = None
    assigned_agent: Optional[str] = None
    result: Optional[str] = None


class SubtaskOut(BaseModel):
    id: UUID
    backlog_id: UUID
    title: str
    description: Optional[str] = None
    status: str
    execution_order: int
    assigned_agent: Optional[str] = None
    result: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
