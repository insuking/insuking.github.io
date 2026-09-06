"""Unit tests for the KIS REST client (mocked transport, see test_kis_auth.py note)."""

import httpx
import pytest

from app.core.config import Settings
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.rest_client import KisRestClient
from app.models.domain import AssetType, Exchange, Market

pytestmark = pytest.mark.P3


def _settings() -> Settings:
    return Settings(kis_app_key="test-key", kis_app_secret="test-secret")  # type: ignore[call-arg]


def _mock_client(
    auth_body: dict, quote_body: dict, requests: list[httpx.Request] | None = None
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json=auth_body)
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-price":
            assert request.headers["tr_id"] == "FHKST01010100"
            assert request.headers["authorization"] == "Bearer test-token"
            return httpx.Response(200, json=quote_body)
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")


@pytest.mark.asyncio
async def test_get_quote_parses_response_into_domain_model() -> None:
    requests: list[httpx.Request] = []
    client = _mock_client(
        auth_body={"access_token": "test-token", "expires_in": 86400},
        quote_body={
            "rt_cd": "0",
            "msg1": "정상처리 되었습니다.",
            "output": {"stck_prpr": "71000", "acml_vol": "12345678"},
        },
        requests=requests,
    )
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()))

    quote = await rest.get_quote("005930", market=Market.KOSPI)

    assert quote.symbol == "005930"
    assert quote.asset_type == AssetType.STOCK
    assert quote.exchange == Exchange.KRX
    assert quote.market == Market.KOSPI
    assert quote.price == 71000.0
    assert quote.volume == 12345678.0
    assert quote.exchange_ts == quote.received_ts

    quote_request = next(r for r in requests if "inquire-price" in str(r.url))
    assert quote_request.url.params["FID_INPUT_ISCD"] == "005930"


@pytest.mark.asyncio
async def test_get_quote_raises_on_non_zero_rt_cd() -> None:
    client = _mock_client(
        auth_body={"access_token": "test-token", "expires_in": 86400},
        quote_body={"rt_cd": "1", "msg1": "종목코드 오류", "output": {}},
    )
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()))

    with pytest.raises(KisApiError):
        await rest.get_quote("BADCODE")
