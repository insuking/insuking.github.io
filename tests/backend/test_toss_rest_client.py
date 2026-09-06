"""Unit tests for the Toss REST client (mocked transport, see test_toss_auth.py note)."""

import time

import httpx
import pytest

from app.core.config import Settings
from app.integrations.toss.auth import TossAuth
from app.integrations.toss.errors import TossApiError, TossRateLimitError
from app.integrations.toss.rest_client import TossRestClient, mask_account_identifier

pytestmark = pytest.mark.P5


def _settings() -> Settings:
    return Settings(toss_client_id="test-id", toss_client_secret="test-secret")  # type: ignore[call-arg]


def _client_and_rest(handler) -> tuple[httpx.AsyncClient, TossRestClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://mock.toss.test"
    )
    rest = TossRestClient(client, TossAuth(client=client, settings=_settings()), base_backoff_seconds=0.0)
    return client, rest


def _auth_ok(request: httpx.Request) -> httpx.Response | None:
    if request.url.path == "/oauth2/token":
        return httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
    return None


# --- account masking -------------------------------------------------------


def test_mask_account_identifier_keeps_last_four() -> None:
    assert mask_account_identifier("1234567890") == "******7890"


def test_mask_account_identifier_shorter_than_visible_masks_fully() -> None:
    assert mask_account_identifier("12") == "**"


# --- happy path endpoints ----------------------------------------------------


@pytest.mark.asyncio
async def test_get_accounts_unwraps_result_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.url.path == "/api/v1/accounts"
        return httpx.Response(200, json={"result": [{"accountSeq": "SEQ-1"}]})

    _client, rest = _client_and_rest(handler)
    accounts = await rest.get_accounts()

    assert accounts == [{"accountSeq": "SEQ-1"}]


@pytest.mark.asyncio
async def test_get_holdings_sends_account_seq_param() -> None:
    seen_params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        seen_params.update(dict(request.url.params))
        return httpx.Response(200, json={"result": {"holdings": []}})

    _client, rest = _client_and_rest(handler)
    await rest.get_holdings("SEQ-1")

    assert seen_params == {"accountSeq": "SEQ-1"}


@pytest.mark.asyncio
async def test_get_orders_includes_status_when_given() -> None:
    seen_params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        seen_params.update(dict(request.url.params))
        return httpx.Response(200, json={"result": []})

    _client, rest = _client_and_rest(handler)
    await rest.get_orders("SEQ-1", status="OPEN")

    assert seen_params == {"accountSeq": "SEQ-1", "status": "OPEN"}


@pytest.mark.asyncio
async def test_get_buying_power_defaults_currency_to_krw() -> None:
    seen_params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        seen_params.update(dict(request.url.params))
        return httpx.Response(200, json={"result": {"amount": "0"}})

    _client, rest = _client_and_rest(handler)
    await rest.get_buying_power("SEQ-1")

    assert seen_params == {"accountSeq": "SEQ-1", "currency": "KRW"}


# --- error handling ----------------------------------------------------------


@pytest.mark.asyncio
async def test_api_error_parses_nested_error_object() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        return httpx.Response(
            400,
            json={"error": {"code": "INVALID_ACCOUNT", "message": "no such account"}},
            headers={"x-request-id": "req-123"},
        )

    _client, rest = _client_and_rest(handler)

    with pytest.raises(TossApiError) as exc_info:
        await rest.get_accounts()

    err = exc_info.value
    assert err.status_code == 400
    assert err.code == "INVALID_ACCOUNT"
    assert err.message == "no such account"
    assert err.request_id == "req-123"


@pytest.mark.asyncio
async def test_api_error_falls_back_to_flat_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        return httpx.Response(500, json={"code": "INTERNAL", "message": "boom"})

    _client, rest = _client_and_rest(handler)

    with pytest.raises(TossApiError) as exc_info:
        await rest.get_accounts()

    assert exc_info.value.code == "INTERNAL"
    assert exc_info.value.message == "boom"


@pytest.mark.asyncio
async def test_api_error_handles_string_error_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        return httpx.Response(403, json={"error": "forbidden", "error_description": "no access"})

    _client, rest = _client_and_rest(handler)

    with pytest.raises(TossApiError) as exc_info:
        await rest.get_accounts()

    assert exc_info.value.code == "forbidden"
    assert exc_info.value.message == "no access"


# --- rate limiting -------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_retries_then_succeeds() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(429, json={"error": "rate_limited"})
        return httpx.Response(200, json={"result": [{"accountSeq": "SEQ-1"}]})

    _client, rest = _client_and_rest(handler)
    accounts = await rest.get_accounts()

    assert accounts == [{"accountSeq": "SEQ-1"}]
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_rate_limit_gives_up_after_max_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        return httpx.Response(429, json={"error": "rate_limited"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://mock.toss.test"
    )
    rest = TossRestClient(
        client,
        TossAuth(client=client, settings=_settings()),
        max_retries=2,
        base_backoff_seconds=0.0,
    )

    with pytest.raises(TossRateLimitError):
        await rest.get_accounts()


@pytest.mark.asyncio
async def test_rate_limit_honors_retry_after_header() -> None:
    attempts = {"n": 0}
    start = time.monotonic()

    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        attempts["n"] += 1
        if attempts["n"] < 2:
            return httpx.Response(429, headers={"retry-after": "0.05"}, json={"error": "rate_limited"})
        return httpx.Response(200, json={"result": []})

    _client, rest = _client_and_rest(handler)
    await rest.get_accounts()

    assert time.monotonic() - start >= 0.05
