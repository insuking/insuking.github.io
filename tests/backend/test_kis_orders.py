"""P29: KIS order placement/cancel (mocked HTTP) - field layout confirmed
against KIS's public sample repo, see orders.py's module docstring for
the exact provenance of each field.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.orders import ORDER_DIVISION_MARKET, KisOrderClient

pytestmark = pytest.mark.P29


def _settings() -> Settings:
    return Settings(kis_app_key="test-key", kis_app_secret="test-secret")  # type: ignore[call-arg]


def _client(handler: httpx.MockTransport | object) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_place_order_buy_uses_the_paper_buy_tr_id_by_default() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/trading/order-cash":
            assert request.headers["tr_id"] == "VTTC0012U"
            return httpx.Response(
                200,
                json={
                    "rt_cd": "0",
                    "msg1": "정상처리 되었습니다.",
                    "output": {"KRX_FWDG_ORD_ORGNO": "06010", "ODNO": "0000117057", "ORD_TMD": "121052"},
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = _client(handler)
    order_client = KisOrderClient(
        client, KisAuth(client=client, settings=_settings()), "12345678", "01", paper_trading=True
    )

    result = await order_client.place_order(symbol="005930", side="BUY", quantity="1", price="71000")

    assert result["output"]["ODNO"] == "0000117057"
    order_request = next(r for r in requests if "order-cash" in str(r.url))
    body = json.loads(order_request.read())
    assert body["CANO"] == "12345678"
    assert body["ACNT_PRDT_CD"] == "01"
    assert body["PDNO"] == "005930"
    assert body["ORD_QTY"] == "1"
    assert body["ORD_UNPR"] == "71000"
    assert body["ORD_DVSN"] == "00"


@pytest.mark.asyncio
async def test_place_order_sell_uses_the_real_sell_tr_id_when_not_paper_trading() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/trading/order-cash":
            assert request.headers["tr_id"] == "TTTC0011U"
            return httpx.Response(200, json={"rt_cd": "0", "output": {"ODNO": "1"}})
        raise AssertionError(f"unexpected request: {request.url}")

    client = _client(handler)
    order_client = KisOrderClient(
        client, KisAuth(client=client, settings=_settings()), "12345678", "01", paper_trading=False
    )

    await order_client.place_order(symbol="005930", side="SELL", quantity="1", price="71000")


@pytest.mark.asyncio
async def test_place_order_rejects_an_invalid_side() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "t", "expires_in": 1})

    client = _client(handler)
    order_client = KisOrderClient(client, KisAuth(client=client, settings=_settings()), "12345678", "01")

    with pytest.raises(ValueError):
        await order_client.place_order(symbol="005930", side="HOLD", quantity="1", price="71000")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_place_order_market_order_sends_zero_price() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/trading/order-cash":
            body = json.loads(request.read())
            assert body["ORD_UNPR"] == "0"
            assert body["ORD_DVSN"] == ORDER_DIVISION_MARKET
            return httpx.Response(200, json={"rt_cd": "0", "output": {"ODNO": "1"}})
        raise AssertionError(f"unexpected request: {request.url}")

    client = _client(handler)
    order_client = KisOrderClient(client, KisAuth(client=client, settings=_settings()), "12345678", "01")

    await order_client.place_order(symbol="005930", side="BUY", quantity="1", order_division=ORDER_DIVISION_MARKET)


@pytest.mark.asyncio
async def test_place_order_raises_on_non_zero_rt_cd() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/trading/order-cash":
            return httpx.Response(200, json={"rt_cd": "1", "msg1": "주문가능금액을 초과하였습니다."})
        raise AssertionError(f"unexpected request: {request.url}")

    client = _client(handler)
    order_client = KisOrderClient(client, KisAuth(client=client, settings=_settings()), "12345678", "01")

    with pytest.raises(KisApiError):
        await order_client.place_order(symbol="005930", side="BUY", quantity="1", price="71000")


@pytest.mark.asyncio
async def test_cancel_order_uses_the_cancel_tr_id_and_original_order_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/trading/order-rvsecncl":
            assert request.headers["tr_id"] == "VTTC0013U"
            return httpx.Response(200, json={"rt_cd": "0", "output": {"ODNO": "0000117058"}})
        raise AssertionError(f"unexpected request: {request.url}")

    client = _client(handler)
    order_client = KisOrderClient(client, KisAuth(client=client, settings=_settings()), "12345678", "01")

    await order_client.cancel_order(krx_fwdg_ord_orgno="06010", original_order_no="0000117057", symbol="005930")

    cancel_request = next(r for r in requests if "order-rvsecncl" in str(r.url))
    body = json.loads(cancel_request.read())
    assert body["KRX_FWDG_ORD_ORGNO"] == "06010"
    assert body["ORGN_ODNO"] == "0000117057"
    assert body["RVSE_CNCL_DVSN_CD"] == "02"
    assert body["QTY_ALL_ORD_YN"] == "Y"
