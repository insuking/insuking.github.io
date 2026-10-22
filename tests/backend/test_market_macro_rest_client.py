"""P38: MarketMacroRestClient parsing against Yahoo Finance's documented
chart-API JSON shape (mocked transport - see test_kis_rest_client.py's
own note on why: this project's egress to query1.finance.yahoo.com is
untested from inside this sandbox, so parsing correctness is proven
against the real, stable response shape instead of a live call)."""

from __future__ import annotations

import httpx
import pytest

from app.integrations.market_macro.errors import MarketMacroApiError
from app.integrations.market_macro.rest_client import MarketMacroRestClient

pytestmark = pytest.mark.P38


def _client(handler) -> httpx.AsyncClient:  # type: ignore[no-untyped-def]
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.macro.test")


def _chart_body(price: float, previous_close: float) -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "^GSPC",
                        "regularMarketPrice": price,
                        "previousClose": previous_close,
                    },
                    "timestamp": [1, 2],
                    "indicators": {"quote": [{"close": [previous_close, price]}]},
                }
            ],
            "error": None,
        }
    }


async def test_get_quote_parses_price_and_previous_close() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v8/finance/chart/^GSPC"
        return httpx.Response(200, json=_chart_body(5100.0, 5000.0))

    rest = MarketMacroRestClient(_client(handler))
    quote = await rest.get_quote("^GSPC")

    assert quote.symbol == "^GSPC"
    assert quote.price == 5100.0
    assert quote.previous_close == 5000.0
    assert quote.change_pct == pytest.approx(2.0)


async def test_get_quote_falls_back_to_chart_previous_close_when_previous_close_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _chart_body(5100.0, 5000.0)
        del body["chart"]["result"][0]["meta"]["previousClose"]
        body["chart"]["result"][0]["meta"]["chartPreviousClose"] = 5000.0
        return httpx.Response(200, json=body)

    rest = MarketMacroRestClient(_client(handler))
    quote = await rest.get_quote("^GSPC")

    assert quote.previous_close == 5000.0


async def test_get_quote_falls_back_to_close_series_when_meta_has_no_previous_close() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = _chart_body(5100.0, 5000.0)
        del body["chart"]["result"][0]["meta"]["previousClose"]
        return httpx.Response(200, json=body)

    rest = MarketMacroRestClient(_client(handler))
    quote = await rest.get_quote("^GSPC")

    assert quote.price == 5100.0
    assert quote.previous_close == 5000.0


async def test_get_quote_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    rest = MarketMacroRestClient(_client(handler))
    with pytest.raises(MarketMacroApiError):
        await rest.get_quote("^GSPC")


async def test_get_quote_raises_on_api_reported_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"chart": {"result": None, "error": {"code": "Not Found"}}})

    rest = MarketMacroRestClient(_client(handler))
    with pytest.raises(MarketMacroApiError):
        await rest.get_quote("BADSYMBOL")


async def test_get_quote_raises_on_empty_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"chart": {"result": [], "error": None}})

    rest = MarketMacroRestClient(_client(handler))
    with pytest.raises(MarketMacroApiError):
        await rest.get_quote("^GSPC")


async def test_get_quote_raises_when_no_usable_price_data_anywhere() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "chart": {
                    "result": [{"meta": {}, "indicators": {"quote": [{"close": [None]}]}}],
                    "error": None,
                }
            },
        )

    rest = MarketMacroRestClient(_client(handler))
    with pytest.raises(MarketMacroApiError):
        await rest.get_quote("^GSPC")
