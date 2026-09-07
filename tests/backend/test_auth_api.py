"""P21 acceptance: the Kakao login HTTP API, end-to-end against the real
app and real local Postgres/Redis via httpx.ASGITransport - only `KakaoAuth`
itself is mocked (its own HTTP behavior is already unit-tested in
test_kakao_auth.py; this file is about auth.py's state-CSRF handling, error
mapping, and KakaoTokenStore wiring, per docs/MASTER_SPEC.md: mocks are
allowed in unit tests, never in integration tests).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.models import KakaoAccount
from app.db.redis_client import get_redis
from app.db.session import session_scope
from app.integrations.kakao.auth import KakaoAuth
from app.integrations.kakao.errors import KakaoAuthError
from app.integrations.kakao.token_store import KakaoTokenStore
from app.main import app

pytestmark = [pytest.mark.P21, pytest.mark.asyncio]

_TEST_KAKAO_USER_ID = "kakao-uid-test-auth-api"


@pytest.fixture(autouse=True)
async def _configure_kakao():  # type: ignore[no-untyped-def]
    settings = get_settings()
    original_id, original_uri = settings.kakao_client_id, settings.kakao_redirect_uri
    settings.kakao_client_id = "test-rest-key"
    settings.kakao_redirect_uri = "https://example.com/callback"
    yield
    settings.kakao_client_id, settings.kakao_redirect_uri = original_id, original_uri


@pytest.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(KakaoAccount).where(KakaoAccount.user_id == _TEST_KAKAO_USER_ID))
        await session.commit()


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _issue_state() -> str:
    async with await _client() as client:
        response = await client.get("/api/auth/kakao/login-url")
    assert response.status_code == 200
    url = response.json()["authorize_url"]
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(url).query)["state"][0]


def _fake_tokens():  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    from app.integrations.kakao.auth import KakaoTokens

    return KakaoTokens(
        access_token="fake-access",
        refresh_token="fake-refresh",
        access_expires_at=now + timedelta(hours=6),
        refresh_expires_at=now + timedelta(days=60),
    )


async def test_login_url_contains_state_and_authorize_endpoint() -> None:
    async with await _client() as client:
        response = await client.get("/api/auth/kakao/login-url")
    assert response.status_code == 200
    url = response.json()["authorize_url"]
    assert "kauth.kakao.com" in url
    assert "state=" in url


async def test_login_url_503_when_kakao_not_configured() -> None:
    settings = get_settings()
    settings.kakao_client_id = ""
    async with await _client() as client:
        response = await client.get("/api/auth/kakao/login-url")
    assert response.status_code == 503


async def test_callback_rejects_unknown_state() -> None:
    async with await _client() as client:
        response = await client.post(
            "/api/auth/kakao/callback", json={"code": "irrelevant", "state": "never-issued"}
        )
    assert response.status_code == 410


async def test_callback_rejects_reused_state() -> None:
    state = await _issue_state()
    with patch.object(KakaoAuth, "exchange_code", new=AsyncMock(return_value=_fake_tokens())), patch.object(
        KakaoAuth, "get_user_id", new=AsyncMock(return_value=_TEST_KAKAO_USER_ID)
    ):
        async with await _client() as client:
            first = await client.post("/api/auth/kakao/callback", json={"code": "abc", "state": state})
            assert first.status_code == 200

            second = await client.post("/api/auth/kakao/callback", json={"code": "abc", "state": state})
    assert second.status_code == 410


async def test_callback_success_persists_kakao_account_and_returns_user_id() -> None:
    state = await _issue_state()
    with patch.object(KakaoAuth, "exchange_code", new=AsyncMock(return_value=_fake_tokens())), patch.object(
        KakaoAuth, "get_user_id", new=AsyncMock(return_value=_TEST_KAKAO_USER_ID)
    ):
        async with await _client() as client:
            response = await client.post(
                "/api/auth/kakao/callback", json={"code": "abc", "state": state}
            )

    assert response.status_code == 200
    assert response.json()["user_id"] == _TEST_KAKAO_USER_ID

    async with session_scope() as session:
        result = await session.execute(
            select(KakaoAccount).where(KakaoAccount.user_id == _TEST_KAKAO_USER_ID)
        )
        account = result.scalar_one()
    assert account.kakao_user_id == _TEST_KAKAO_USER_ID
    assert account.access_token == "fake-access"


async def test_callback_maps_kakao_auth_error_to_401() -> None:
    state = await _issue_state()
    with patch.object(
        KakaoAuth, "exchange_code", new=AsyncMock(side_effect=KakaoAuthError("bad code"))
    ):
        async with await _client() as client:
            response = await client.post(
                "/api/auth/kakao/callback", json={"code": "bad", "state": state}
            )
    assert response.status_code == 401


async def test_callback_503_when_kakao_not_configured() -> None:
    # Seed a state directly (bypassing login-url, which itself needs Kakao
    # configured) so only the callback's own configuration check is under
    # test.
    redis = get_redis()
    settings = get_settings()
    state = "manually-seeded-state"
    await redis.set(f"kakao_oauth_state:{state}", "1", ex=settings.kakao_oauth_state_ttl_seconds)
    settings.kakao_client_id = ""

    async with await _client() as client:
        response = await client.post("/api/auth/kakao/callback", json={"code": "abc", "state": state})
    assert response.status_code == 503


async def test_login_then_get_valid_access_token_works_without_further_network_calls() -> None:
    """End-to-end sanity check: after a real callback, `KakaoTokenStore`
    (P12) can serve this user's access token purely from what the callback
    persisted - the exact integration point `approvals.py`'s auth check
    depends on."""
    state = await _issue_state()
    with patch.object(KakaoAuth, "exchange_code", new=AsyncMock(return_value=_fake_tokens())), patch.object(
        KakaoAuth, "get_user_id", new=AsyncMock(return_value=_TEST_KAKAO_USER_ID)
    ):
        async with await _client() as client:
            await client.post("/api/auth/kakao/callback", json={"code": "abc", "state": state})

    async with httpx.AsyncClient(timeout=10.0) as http_client, session_scope() as session:
        store = KakaoTokenStore(session, KakaoAuth(client=http_client))
        token = await store.get_valid_access_token(_TEST_KAKAO_USER_ID)
    assert token == "fake-access"
