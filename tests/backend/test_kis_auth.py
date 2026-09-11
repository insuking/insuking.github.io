"""Unit tests for KIS auth (mocked HTTP transport - not a real KIS connection).

Per docs/MASTER_SPEC.md: mocks are allowed in unit tests, never in
integration tests. These tests verify our request/response handling, not
that KIS's servers are reachable - see test_kis_integration.py for the real
(credential-gated) connectivity check.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import Settings
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisAuthError, KisNotConfiguredError

pytestmark = pytest.mark.P3


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"kis_app_key": "test-key", "kis_app_secret": "test-secret"}
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://mock.kis.test"
    )


@pytest.mark.asyncio
async def test_get_access_token_raises_when_not_configured() -> None:
    auth = KisAuth(client=_client_with(lambda r: httpx.Response(200)), settings=_settings(kis_app_key=""))
    with pytest.raises(KisNotConfiguredError):
        await auth.get_access_token()


@pytest.mark.asyncio
async def test_get_access_token_parses_and_caches() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/oauth2/tokenP"
        return httpx.Response(200, json={"access_token": "abc123", "expires_in": 86400})

    auth = KisAuth(client=_client_with(handler), settings=_settings())

    token1 = await auth.get_access_token()
    token2 = await auth.get_access_token()

    assert token1 == "abc123"
    assert token2 == "abc123"
    assert len(calls) == 1  # second call served from cache, no new HTTP request


@pytest.mark.asyncio
async def test_get_access_token_refreshes_after_expiry() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"access_token": f"token-{call_count}", "expires_in": 86400})

    auth = KisAuth(client=_client_with(handler), settings=_settings())
    await auth.get_access_token()

    # Force the cached token to look expired without waiting 24h in a test.
    assert auth._token is not None
    auth._token.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    token2 = await auth.get_access_token()
    assert token2 == "token-2"
    assert call_count == 2


@pytest.mark.asyncio
async def test_get_access_token_raises_on_error_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error_description": "invalid appkey"})

    auth = KisAuth(client=_client_with(handler), settings=_settings())
    with pytest.raises(KisAuthError):
        await auth.get_access_token()


@pytest.mark.asyncio
async def test_get_ws_approval_key_parses_and_caches() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/oauth2/Approval"
        return httpx.Response(200, json={"approval_key": "approval-xyz"})

    auth = KisAuth(client=_client_with(handler), settings=_settings())

    key1 = await auth.get_ws_approval_key()
    key2 = await auth.get_ws_approval_key()

    assert key1 == "approval-xyz"
    assert key2 == "approval-xyz"
    assert len(calls) == 1
