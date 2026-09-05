import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import DOMAIN_MODELS

pytestmark = pytest.mark.P1

client = TestClient(app)

EXPECTED_MODEL_NAMES = {model.__name__ for model in DOMAIN_MODELS}


def test_domain_schema_endpoint_returns_200() -> None:
    response = client.get("/internal/domain-schema")
    assert response.status_code == 200


def test_domain_schema_contains_every_p1_model() -> None:
    response = client.get("/internal/domain-schema")
    body = response.json()

    assert set(body.keys()) == EXPECTED_MODEL_NAMES


def test_domain_schema_entries_are_valid_json_schema_objects() -> None:
    response = client.get("/internal/domain-schema")
    body = response.json()

    for name, schema in body.items():
        assert schema.get("type") == "object", f"{name} schema missing object type"
        assert "properties" in schema, f"{name} schema missing properties"


def test_recommendation_schema_exposes_partial_profit_fields() -> None:
    response = client.get("/internal/domain-schema")
    recommendation_schema = response.json()["Recommendation"]

    for field in ("t1_percent", "t2_percent", "runner_percent", "expected_max_loss"):
        assert field in recommendation_schema["properties"]


def test_openapi_includes_domain_schema_route() -> None:
    openapi = client.get("/openapi.json").json()
    assert "/internal/domain-schema" in openapi["paths"]
