"""Unit tests for the Kakao 'send to me' notifier (mocked HTTP transport)."""

import json

import httpx
import pytest

from app.core.config import Settings
from app.integrations.kakao.errors import KakaoNotConfiguredError, KakaoNotificationError
from app.integrations.kakao.notify import KakaoNotifier

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


@pytest.mark.asyncio
async def test_send_approval_link_raises_when_not_configured() -> None:
    notifier = KakaoNotifier(
        client=_client_with(lambda r: httpx.Response(200)), settings=_settings(kakao_client_id="")
    )
    with pytest.raises(KakaoNotConfiguredError):
        await notifier.send_approval_link("token", "https://example.com/approve/1", "message")


@pytest.mark.asyncio
async def test_send_approval_link_posts_expected_template_and_auth_header() -> None:
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json={"result_code": 0})

    notifier = KakaoNotifier(client=_client_with(handler), settings=_settings())
    await notifier.send_approval_link("access-tok", "https://example.com/approve/1", "삼성전자 매수 승인 요청")

    assert len(seen_requests) == 1
    request = seen_requests[0]
    assert request.url.path == "/v2/api/talk/memo/default/send"
    assert request.headers["Authorization"] == "Bearer access-tok"

    body = dict(httpx.QueryParams(request.content.decode()))
    template = json.loads(body["template_object"])
    assert template["object_type"] == "text"
    assert template["text"] == "삼성전자 매수 승인 요청"
    assert template["link"]["web_url"] == "https://example.com/approve/1"


@pytest.mark.asyncio
async def test_send_approval_link_raises_on_nonzero_result_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result_code": -401})

    notifier = KakaoNotifier(client=_client_with(handler), settings=_settings())
    with pytest.raises(KakaoNotificationError):
        await notifier.send_approval_link("token", "https://example.com/approve/1", "message")


@pytest.mark.asyncio
async def test_send_approval_link_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": -401, "msg": "this access token does not exist"})

    notifier = KakaoNotifier(client=_client_with(handler), settings=_settings())
    with pytest.raises(KakaoNotificationError):
        await notifier.send_approval_link("bad-token", "https://example.com/approve/1", "message")
