import httpx
import pytest

from app.integrations.upbit.errors import UpbitApiError
from app.integrations.upbit.rest_client import UpbitRestClient, verify_price_consistency

pytestmark = pytest.mark.P7


def _client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://mock.upbit.test"
    )


@pytest.mark.asyncio
async def test_get_ticker_price_returns_trade_price() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/ticker"
        assert request.url.params["markets"] == "KRW-BTC"
        return httpx.Response(200, json=[{"market": "KRW-BTC", "trade_price": 71000000.0}])

    rest = UpbitRestClient(_client_with(handler))
    price = await rest.get_ticker_price("KRW-BTC")

    assert price == 71000000.0


@pytest.mark.asyncio
async def test_get_candles_parses_into_domain_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/candles/minutes/1"
        return httpx.Response(
            200,
            json=[
                {
                    "market": "KRW-BTC",
                    "candle_date_time_utc": "2026-01-05T09:30:00",
                    "opening_price": 100.0,
                    "high_price": 110.0,
                    "low_price": 95.0,
                    "trade_price": 105.0,
                    "candle_acc_trade_volume": 12.5,
                }
            ],
        )

    rest = UpbitRestClient(_client_with(handler))
    candles = await rest.get_candles("KRW-BTC", unit_minutes=1, count=1)

    assert len(candles) == 1
    candle = candles[0]
    assert candle.symbol == "KRW-BTC"
    assert candle.interval == "1m"
    assert candle.open == 100.0
    assert candle.close == 105.0
    assert candle.volume == 12.5


@pytest.mark.asyncio
async def test_get_ticker_price_raises_on_error_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"error": {"name": "invalid_market", "message": "no such market"}}
        )

    rest = UpbitRestClient(_client_with(handler))

    with pytest.raises(UpbitApiError) as exc_info:
        await rest.get_ticker_price("BAD-MARKET")

    assert exc_info.value.status_code == 404
    assert exc_info.value.name == "invalid_market"
    assert exc_info.value.message == "no such market"


def test_verify_price_consistency_within_tolerance() -> None:
    assert verify_price_consistency(ws_price=100.0, rest_price=101.0, max_deviation=0.02) is True


def test_verify_price_consistency_outside_tolerance() -> None:
    assert verify_price_consistency(ws_price=100.0, rest_price=110.0, max_deviation=0.02) is False


def test_verify_price_consistency_zero_rest_price_is_inconsistent() -> None:
    assert verify_price_consistency(ws_price=100.0, rest_price=0.0) is False
