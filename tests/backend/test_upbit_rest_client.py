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
async def test_get_tickers_summary_parses_multiple_markets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/ticker"
        assert request.url.params["markets"] == "KRW-BTC,KRW-ETH"
        return httpx.Response(
            200,
            json=[
                {"market": "KRW-BTC", "trade_price": 82_000_000.0, "acc_trade_price_24h": 1.5e11},
                {"market": "KRW-ETH", "trade_price": 4_500_000.0, "acc_trade_price_24h": 8.0e10},
            ],
        )

    rest = UpbitRestClient(_client_with(handler))
    summaries = await rest.get_tickers_summary(["KRW-BTC", "KRW-ETH"])

    assert [s.market for s in summaries] == ["KRW-BTC", "KRW-ETH"]
    assert summaries[0].trade_price == 82_000_000.0
    assert summaries[0].acc_trade_price_24h == 1.5e11


@pytest.mark.asyncio
async def test_get_tickers_summary_empty_markets_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not make an HTTP request for an empty market list")

    rest = UpbitRestClient(_client_with(handler))
    assert await rest.get_tickers_summary([]) == []


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


@pytest.mark.asyncio
async def test_get_retries_a_429_and_succeeds() -> None:
    """A real scan against Upbit's real market once tripped exactly this
    (429 from firing get_candles() for many markets too fast) - see
    docs/UPBIT_NOTES.md. The retry must not surface the 429 as a hard
    failure when a later attempt succeeds."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(429, json={"error": {"name": "too_many_requests"}})
        return httpx.Response(200, json=[{"market": "KRW-BTC", "trade_price": 71000000.0}])

    rest = UpbitRestClient(_client_with(handler), rate_limit_backoff_seconds=0.01)
    price = await rest.get_ticker_price("KRW-BTC")

    assert price == 71000000.0
    assert calls == 3


@pytest.mark.asyncio
async def test_get_raises_after_exhausting_429_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"name": "too_many_requests"}})

    rest = UpbitRestClient(_client_with(handler), rate_limit_backoff_seconds=0.01)

    with pytest.raises(UpbitApiError) as exc_info:
        await rest.get_ticker_price("KRW-BTC")

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_throttle_paces_concurrent_requests_under_the_configured_rate() -> None:
    import asyncio
    import time

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"market": "KRW-BTC", "trade_price": 1.0}])

    rest = UpbitRestClient(_client_with(handler), max_requests_per_second=20.0)

    start = time.monotonic()
    await asyncio.gather(*(rest.get_ticker_price("KRW-BTC") for _ in range(5)))
    elapsed = time.monotonic() - start

    # 5 requests at 20/sec must take at least 4 intervals (0.2s) - a bug that
    # skipped throttling for concurrent callers would finish near-instantly.
    assert elapsed >= 0.19


def test_verify_price_consistency_within_tolerance() -> None:
    assert verify_price_consistency(ws_price=100.0, rest_price=101.0, max_deviation=0.02) is True


def test_verify_price_consistency_outside_tolerance() -> None:
    assert verify_price_consistency(ws_price=100.0, rest_price=110.0, max_deviation=0.02) is False


def test_verify_price_consistency_zero_rest_price_is_inconsistent() -> None:
    assert verify_price_consistency(ws_price=100.0, rest_price=0.0) is False
