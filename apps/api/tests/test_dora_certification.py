"""Testes de certificacao DORA: idempotencia de outcomes e payload de MTTR."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.deployment import DeploymentOutcome
from app.models.handoff import AgentRunEvent
from app.routers.deployments import create_deployment_outcome
from app.schemas.deployment import DeploymentOutcomeCreate
from app.services.incident_parser import IncidentParser


def _outcome_create(proof_id="proof-abc"):
    return DeploymentOutcomeCreate(
        proof_id=proof_id,
        project="workdev",
        artifact_fingerprint="ab" * 32,
        outcome="success",
    )


def _existing_outcome(**overrides):
    existing = MagicMock(spec=DeploymentOutcome)
    fields = {
        "proof_id": "proof-abc",
        "project": "workdev",
        "artifact_fingerprint": "ab" * 32,
        "outcome": "success",
        "commit_sha": None,
    }
    fields.update(overrides)
    for key, value in fields.items():
        setattr(existing, key, value)
    return existing


def test_post_outcomes_retry_identico_retorna_200():
    existing = _existing_outcome()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing
    response = MagicMock()

    result = create_deployment_outcome(_outcome_create(), response, db)

    assert result is existing
    assert response.status_code == 200
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize(
    "campo",
    ["project", "artifact_fingerprint", "outcome", "commit_sha"],
)
def test_post_outcomes_payload_conflitante_retorna_409(campo):
    existing = _existing_outcome(**{campo: "valor-divergente"})
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing
    response = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        create_deployment_outcome(_outcome_create(), response, db)

    assert exc_info.value.status_code == 409
    assert campo in exc_info.value.detail
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_post_outcomes_cria_quando_proof_id_novo():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    response = MagicMock()

    create_deployment_outcome(_outcome_create("proof-novo"), response, db)

    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_resolution_event_carrega_detected_at_do_incidente_original():
    detected = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc).isoformat()
    original = MagicMock(spec=AgentRunEvent)
    original.payload = {"detected_at": detected}

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = original

    created = {}

    def fake_add(event):
        created["event"] = event

    db.add.side_effect = fake_add
    parser = IncidentParser(db)
    parser.create_resolution_event(uuid4(), {"incident_type": "service_outage"})

    payload = created["event"].payload
    assert payload["detected_at"] == detected
    assert payload["resolved_at"] is not None
    # Query de MTTR em /api/metrics/executive exige as duas chaves:
    assert "detected_at" in payload and "resolved_at" in payload
