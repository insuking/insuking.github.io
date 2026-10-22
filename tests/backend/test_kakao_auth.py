"""Unit tests for Kakao OAuth (mocked HTTP transport - not a real Kakao
connection). Per docs/MASTER_SPEC.md: mocks are allowed in unit tests, never
in integration tests - see test_kakao_integration.py for the real
(credential-gated) connectivity check.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.config import Settings
from app.integrations.kakao.auth import KakaoAuth, KakaoTokens
from app.integrations.kakao.errors import KakaoAuthError, KakaoNotConfiguredError

pytestmark = pytest.mark.P12


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "kakao_client_id": "test-rest-key",
        "kakao_redirect_uri": "https://example.com/callback",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _tokens(**overrides: object) -> KakaoTokens:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "access_token": "old-access",
        "refresh_token": "old-refresh",
        "access_expires_at": now + timedelta(hours=6),
        "refresh_expires_at": now + timedelta(days=60),
    }
    defaults.update(overrides)
    return KakaoTokens(**defaults)  # type: ignore[arg-type]


# --- authorize_url -----------------------------------------------------


def test_authorize_url_raises_when_not_configured() -> None:
    auth = KakaoAuth(client=_client_with(lambda r: httpx.Response(200)), settings=_settings(kakao_client_id=""))
    with pytest.raises(KakaoNotConfiguredError):
        auth.authorize_url()


def test_authorize_url_includes_client_id_redirect_and_response_type() -> None:
    auth = KakaoAuth(client=_client_with(lambda r: httpx.Response(200)), settings=_settings())
    url = auth.authorize_url(state="xyz")

    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "kauth.kakao.com"
    assert parsed.path == "/oauth/authorize"
    query = parse_qs(parsed.query)
    assert query["client_id"] == ["test-rest-key"]
    assert query["redirect_uri"] == ["https://example.com/callback"]
    assert query["response_type"] == ["code"]
    assert query["state"] == ["xyz"]


# --- exchange_code -------------------------------------------------------


@pytest.mark.asyncio
async def test_exchange_code_sends_authorization_code_grant_without_secret() -> None:
    seen_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/token"
        seen_bodies.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(
            200,
            json={
                "token_type": "bearer",
                "access_token": "acc-1",
                "expires_in": 21599,
                "refresh_token": "ref-1",
                "refresh_token_expires_in": 5184000,
                "scope": "talk_message",
            },
        )

    auth = KakaoAuth(client=_client_with(handler), settings=_settings())
    tokens = await auth.exchange_code("auth-code-123")

    assert seen_bodies == [
        {
            "grant_type": "authorization_code",
            "client_id": "test-rest-key",
            "redirect_uri": "https://example.com/callback",
            "code": "auth-code-123",
        }
    ]
    assert tokens.access_token == "acc-1"
    assert tokens.refresh_token == "ref-1"
    assert tokens.scope == "talk_message"


@pytest.mark.asyncio
async def test_exchange_code_includes_client_secret_when_configured() -> None:
    seen_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_bodies.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(
            200,
            json={
                "access_token": "acc",
                "expires_in": 3600,
                "refresh_token": "ref",
                "refresh_token_expires_in": 100,
            },
        )

    auth = KakaoAuth(client=_client_with(handler), settings=_settings(kakao_client_secret="shh"))
    await auth.exchange_code("code")

    assert seen_bodies[0]["client_secret"] == "shh"


@pytest.mark.asyncio
async def test_exchange_code_computes_expiry_timestamps() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "acc",
                "expires_in": 3600,
                "refresh_token": "ref",
                "refresh_token_expires_in": 7200,
            },
        )

    before = datetime.now(UTC)
    auth = KakaoAuth(client=_client_with(handler), settings=_settings())
    tokens = await auth.exchange_code("code")
    after = datetime.now(UTC)

    assert before + timedelta(seconds=3600) <= tokens.access_expires_at <= after + timedelta(seconds=3600)
    assert before + timedelta(seconds=7200) <= tokens.refresh_expires_at <= after + timedelta(seconds=7200)


@pytest.mark.asyncio
async def test_exchange_code_raises_on_error_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "bad code"})

    auth = KakaoAuth(client=_client_with(handler), settings=_settings())
    with pytest.raises(KakaoAuthError):
        await auth.exchange_code("bad-code")


@pytest.mark.asyncio
async def test_exchange_code_raises_when_required_field_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # 200 but missing refresh_token - must not silently accept a partial grant.
        return httpx.Response(200, json={"access_token": "acc", "expires_in": 3600})

    auth = KakaoAuth(client=_client_with(handler), settings=_settings())
    with pytest.raises(KakaoAuthError):
        await auth.exchange_code("code")


# --- refresh ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_sends_refresh_token_grant() -> None:
    seen_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_bodies.append(dict(httpx.QueryParams(request.content.decode())))
        return httpx.Response(200, json={"access_token": "new-access", "expires_in": 3600})

    auth = KakaoAuth(client=_client_with(handler), settings=_settings())
    previous = _tokens(refresh_token="ref-abc")
    refreshed = await auth.refresh(previous)

    assert seen_bodies == [
        {"grant_type": "refresh_token", "client_id": "test-rest-key", "refresh_token": "ref-abc"}
    ]
    assert refreshed.access_token == "new-access"


@pytest.mark.asyncio
async def test_refresh_keeps_prior_refresh_token_when_not_reissued() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Kakao only reissues refresh_token when the old one has < 1 month left.
        return httpx.Response(200, json={"access_token": "new-access", "expires_in": 3600})

    auth = KakaoAuth(client=_client_with(handler), settings=_settings())
    previous = _tokens(refresh_token="still-valid-refresh")
    refreshed = await auth.refresh(previous)

    assert refreshed.refresh_token == "still-valid-refresh"
    assert refreshed.refresh_expires_at == previous.refresh_expires_at


@pytest.mark.asyncio
async def test_refresh_adopts_new_refresh_token_when_reissued() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "new-access",
                "expires_in": 3600,
                "refresh_token": "brand-new-refresh",
                "refresh_token_expires_in": 5184000,
            },
        )

    auth = KakaoAuth(client=_client_with(handler), settings=_settings())
    previous = _tokens(refresh_token="about-to-expire")
    refreshed = await auth.refresh(previous)

    assert refreshed.refresh_token == "brand-new-refresh"
    assert refreshed.refresh_expires_at > previous.refresh_expires_at - timedelta(days=1)


@pytest.mark.asyncio
async def test_refresh_raises_on_error_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": -1, "msg": "invalid refresh token"})

    auth = KakaoAuth(client=_client_with(handler), settings=_settings())
    with pytest.raises(KakaoAuthError):
        await auth.refresh(_tokens())


# --- get_user_id -------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_id_parses_numeric_id_as_string() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/user/me"
        assert request.headers["Authorization"] == "Bearer some-token"
        return httpx.Response(200, json={"id": 123456789, "kakao_account": {}})

    auth = KakaoAuth(client=_client_with(handler), settings=_settings())
    user_id = await auth.get_user_id("some-token")

    assert user_id == "123456789"


@pytest.mark.asyncio
async def test_get_user_id_raises_on_error_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": -401, "msg": "this access token does not exist"})

    auth = KakaoAuth(client=_client_with(handler), settings=_settings())
    with pytest.raises(KakaoAuthError):
        await auth.get_user_id("bad-token")
