from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_live_returns_200() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_ready_returns_200_when_dependencies_up() -> None:
    with (
        patch("app.api.health.check_database", new=AsyncMock(return_value=True)),
        patch("app.api.health.check_redis", new=AsyncMock(return_value=True)),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "redis": "ok"}


def test_ready_returns_503_when_database_down() -> None:
    with (
        patch("app.api.health.check_database", new=AsyncMock(return_value=False)),
        patch("app.api.health.check_redis", new=AsyncMock(return_value=True)),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "fail"


def test_ready_returns_503_when_redis_down() -> None:
    with (
        patch("app.api.health.check_database", new=AsyncMock(return_value=True)),
        patch("app.api.health.check_redis", new=AsyncMock(return_value=False)),
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["checks"]["redis"] == "fail"


def test_root_returns_app_metadata() -> None:
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert "name" in body
    assert "environment" in body
