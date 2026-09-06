"""Unit tests for Toss auth (mocked HTTP transport - not a real Toss connection).

Per docs/MASTER_SPEC.md: mocks are allowed in unit tests, never in
integration tests - see test_toss_integration.py for the real
(credential-gated) connectivity check.
"""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import Settings
from app.integrations.toss.auth import TossAuth
from app.integrations.toss.errors import TossAuthError, TossNotConfiguredError

pytestmark = pytest.mark.P5


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"toss_client_id": "test-id", "toss_client_secret": "test-secret"}
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://mock.toss.test"
    )


@pytest.mark.asyncio
async def test_get_access_token_raises_when_not_configured() -> None:
    auth = TossAuth(
        client=_client_with(lambda r: httpx.Response(200)), settings=_settings(toss_client_id="")
    )
    with pytest.raises(TossNotConfiguredError):
        await auth.get_access_token()


@pytest.mark.asyncio
async def test_get_access_token_parses_and_caches() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/oauth2/token"
        return httpx.Response(
            200, json={"access_token": "abc123", "token_type": "Bearer", "expires_in": 3600}
        )

    auth = TossAuth(client=_client_with(handler), settings=_settings())

    token1 = await auth.get_access_token()
    token2 = await auth.get_access_token()

    assert token1 == "abc123"
    assert token2 == "abc123"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_get_access_token_sends_client_credentials_grant() -> None:
    seen_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})

    auth = TossAuth(client=_client_with(handler), settings=_settings())
    await auth.get_access_token()

    assert seen_bodies == [
        {"grant_type": "client_credentials", "client_id": "test-id", "client_secret": "test-secret"}
    ]


@pytest.mark.asyncio
async def test_get_access_token_refreshes_after_expiry() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"access_token": f"token-{call_count}", "expires_in": 3600})

    auth = TossAuth(client=_client_with(handler), settings=_settings())
    await auth.get_access_token()

    assert auth._token is not None
    auth._token.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    token2 = await auth.get_access_token()
    assert token2 == "token-2"
    assert call_count == 2


@pytest.mark.asyncio
async def test_get_access_token_raises_on_error_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error_description": "invalid client"})

    auth = TossAuth(client=_client_with(handler), settings=_settings())
    with pytest.raises(TossAuthError):
        await auth.get_access_token()
