from sqlalchemy import (
    Column, DateTime, Enum, String, Text, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class DeploymentOutcome(Base):
    __tablename__ = "deployment_outcomes"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    proof_id = Column(String(64), nullable=False, index=True)
    project = Column(String(255), nullable=False, index=True)
    artifact_fingerprint = Column(String(64), nullable=False)
    outcome = Column(
        Enum(
            "success", "rolled_back", "hotfixed", "degraded",
            name="deployment_outcome"
        ),
        nullable=False,
        index=True,
    )
    deployed_at = Column(DateTime(timezone=True), nullable=False, index=True)
    deployed_by = Column(String(100), nullable=True)
    commit_sha = Column(String(64), nullable=True)
    deployment_url = Column(Text(), nullable=True)
    postcheck_result = Column(JSONB(), nullable=True)
    error_message = Column(Text(), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
        nullable=False,
    )
