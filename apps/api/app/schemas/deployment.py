from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


DeploymentOutcomeType = Literal["success", "rolled_back", "hotfixed", "degraded"]


class DeploymentOutcomeCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    proof_id: str = Field(min_length=1, max_length=64)
    project: str = Field(min_length=1, max_length=255)
    artifact_fingerprint: str = Field(min_length=1, max_length=64)
    outcome: DeploymentOutcomeType
    deployed_at: datetime | None = None
    deployed_by: str | None = Field(default=None, max_length=100)
    commit_sha: str | None = Field(default=None, max_length=64)
    deployment_url: str | None = None
    postcheck_result: dict | None = None
    error_message: str | None = None


class DeploymentOutcomeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    proof_id: str
    project: str
    artifact_fingerprint: str
    outcome: DeploymentOutcomeType
    deployed_at: datetime
    deployed_by: str | None
    commit_sha: str | None
    deployment_url: str | None
    postcheck_result: dict | None
    error_message: str | None
    created_at: datetime
