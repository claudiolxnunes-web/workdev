from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


PlanStatus = Literal["draft", "approved", "needs_revision", "superseded", "discarded"]
RunStatus = Literal[
    "queued", "running", "blocked", "review", "completed", "failed", "cancelled"
]
AgentName = Literal["codex", "claude", "kimi", "qwen"]


class PlanCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    backlog_id: UUID
    title: str | None = Field(
        default=None, min_length=3,
        validation_alias=AliasChoices("title", "titulo"),
    )
    objective: str = Field(
        min_length=3, validation_alias=AliasChoices("objective", "objetivo")
    )
    scope: str | None = None
    constraints: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    implementation_notes: str | None = None
    created_by: str = "ai_hub"


class PlanUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str | None = Field(
        default=None, min_length=3,
        validation_alias=AliasChoices("title", "titulo"),
    )
    objective: str | None = Field(
        default=None, min_length=3,
        validation_alias=AliasChoices("objective", "objetivo"),
    )
    status: Literal["discarded"] | None = None
    scope: str | None = None
    constraints: list[str] | None = None
    acceptance_criteria: list[str] | None = None
    validation_steps: list[str] | None = None
    implementation_notes: str | None = None


class PlanOut(PlanCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    status: PlanStatus
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    task_title: str | None = None
    project_id: UUID | None = None
    project_name: str | None = None


class BuildRequest(BaseModel):
    agent: AgentName


class RunUpdate(BaseModel):
    status: RunStatus | None = None
    summary: str | None = None
    result: str | None = None
    error: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    deployment_url: str | None = None
    message: str | None = None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plan_id: UUID
    backlog_id: UUID
    agent: AgentName
    status: RunStatus
    summary: str | None = None
    result: str | None = None
    error: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    deployment_url: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    task_title: str | None = None
    project_id: UUID | None = None
    project_name: str | None = None
    plan_version: int | None = None


class RunTransfer(BaseModel):
    agent: AgentName
    reason: str = Field(min_length=1)


class RunEventCreate(BaseModel):
    event_type: str = Field(min_length=2, max_length=40)
    message: str | None = None
    payload: dict = Field(default_factory=dict)


class SubtaskProgress(BaseModel):
    status: Literal["todo", "doing", "done"]
    result: str | None = None
