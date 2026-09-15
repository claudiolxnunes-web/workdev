"""HTTP catalog integration against an isolated SQL database and canonical ORM."""
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import JSON, MetaData, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.ai_routing import AIModelCatalog
from app.routers import ai
from app.services import ai_cost_guard


@pytest.fixture
def catalog_api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    # Preserve canonical columns; adapt only Postgres JSON/default syntax for SQLite.
    table = AIModelCatalog.__table__.to_metadata(MetaData())
    for column in table.columns:
        if isinstance(column.type, JSONB):
            column.type = JSON()
        column.server_default = None
    table.create(engine)
    with Session(engine) as db:
        app = FastAPI()
        app.include_router(ai.router, prefix="/api")
        app.dependency_overrides[ai.get_db] = lambda: db
        with TestClient(app) as client:
            yield client, db
    engine.dispose()


def add_model(db, model, *, provider="openrouter", active=True):
    row = AIModelCatalog(
        id=provider + model, display_name=model, provider=provider, provider_model_id=model,
        category="economic", capabilities=[], allowed_reasoning_efforts=[],
        supports_tools=True, supports_structured_output=False, supports_multimodal=False,
        active=active, is_free=False, requires_confirmation=False, allowed_fallbacks=[],
        input_cost_per_million=Decimal("0.10"), output_cost_per_million=Decimal("0.20"),
    )
    db.add(row)
    db.commit()
    return row


def test_active_catalog_is_dynamic_and_not_limited_to_agent_bindings(catalog_api):
    client, db = catalog_api
    add_model(db, "vendor/alpha")
    add_model(db, "vendor/disabled", active=False)
    add_model(db, "vendor/other", provider="openai")
    assert client.get("/api/ai/models?provider=openrouter").json() == [
        {"provider": "openrouter", "model": "vendor/alpha", "label": "vendor/alpha"},
    ]
    new = add_model(db, "vendor/new-model")
    assert new.agent_slug is None
    response = client.get("/api/ai/models?provider=openrouter")
    assert response.status_code == 200
    assert [row["model"] for row in response.json()] == ["vendor/alpha", "vendor/new-model"]
    new.active = False
    db.commit()
    assert len(client.get("/api/ai/models?provider=openrouter").json()) == 1
    with pytest.raises(ai_cost_guard.CostGuardError, match="desativado"):
        ai_cost_guard.policy_for("openrouter", "vendor/new-model", db)


def test_empty_catalog_and_provider_validation(catalog_api):
    client, db = catalog_api
    assert client.get("/api/ai/models?provider=openrouter").json() == []
    assert client.get("/api/ai/models?provider=unknown").status_code == 422


def test_selected_model_uses_canonical_prices(catalog_api):
    client, db = catalog_api
    add_model(db, "vendor/dynamic")
    model = client.get("/api/ai/models?provider=openrouter").json()[0]["model"]
    policy = ai_cost_guard.policy_for("openrouter", model, db)
    assert policy.input_cost == Decimal("0.10")
    assert policy.output_cost == Decimal("0.20")
