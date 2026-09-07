"""P23: real-market crypto recommendation scan.

Uses `httpx.MockTransport` to stand in for Upbit's real REST API (per
docs/MASTER_SPEC.md: mocks are for unit tests only, never a substitute for
a real connection - see docs/UPBIT_NOTES.md for why the real Upbit
integration test is skipped in this sandbox). This test suite verifies the
*wiring*: candle-order reversal, liquidity prefiltering, ranking, and that
`build_recommendation()`'s own gating (never padding a result with
ineligible candidates) is respected end to end.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.integrations.upbit.rest_client import UpbitRestClient
from app.scan.crypto_scan import scan_crypto_market

pytestmark = pytest.mark.P23

_START = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)


def _bar(open_: float, high: float, low: float, close: float, volume: float) -> tuple:
    return (open_, high, low, close, volume)


def _opening_range_bars(count: int = 15) -> list[tuple]:
    return [_bar(97.0, 100.0, 95.0, 97.0, 10.0) for _ in range(count)]


def _filler_bars(count: int = 4) -> list[tuple]:
    return [_bar(98.0, 99.0, 96.0, 98.0, 10.0) for _ in range(count)]


def _aaa_candles() -> list[tuple]:
    """Strong breakout: closes at 105.5 (above the 100 opening-range high),
    on 20x the average volume, near the top of its own bar's range."""
    return [*_opening_range_bars(), *_filler_bars(), _bar(98.0, 106.0, 100.0, 105.5, 200.0)]


def _bbb_candles() -> list[tuple]:
    """Flat: never crosses the opening-range high - stays in STEALTH, so
    build_recommendation() must reject it rather than padding the result."""
    return [*_opening_range_bars(count=20)]


def _ccc_candles() -> list[tuple]:
    """A weaker breakout than AAA (smaller move, lower volume) - used to
    verify ranking order and the top_n cutoff."""
    return [*_opening_range_bars(), *_filler_bars(), _bar(98.0, 102.0, 99.0, 101.0, 50.0)]


def _btc_candles() -> list[tuple]:
    """A steady uptrend so classify_btc_regime() reads RISK_ON."""
    return [_bar(80_000_000 + i * 40_000, 80_050_000 + i * 40_000, 79_950_000 + i * 40_000, 80_000_000 + i * 40_000, 5.0) for i in range(25)]


def _upbit_candles_json(bars: list[tuple], market: str) -> list[dict]:
    """Build the JSON body Upbit's REST candle endpoint would return: one
    object per bar, **most-recent-first** (see docs/UPBIT_NOTES.md) - the
    reverse of the chronological order `bars` is given in."""
    out = []
    for i, (open_, high, low, close, volume) in enumerate(bars):
        candle_time = _START + timedelta(minutes=i)
        out.append(
            {
                "market": market,
                "candle_date_time_utc": candle_time.strftime("%Y-%m-%dT%H:%M:%S"),
                "opening_price": open_,
                "high_price": high,
                "low_price": low,
                "trade_price": close,
                "candle_acc_trade_volume": volume,
            }
        )
    return list(reversed(out))


_CANDLES_BY_MARKET = {
    "KRW-BTC": _btc_candles(),
    "KRW-AAA": _aaa_candles(),
    "KRW-BBB": _bbb_candles(),
    "KRW-CCC": _ccc_candles(),
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/v1/market/all":
        return httpx.Response(
            200,
            json=[{"market": market, "korean_name": market} for market in _CANDLES_BY_MARKET],
        )
    if path == "/v1/ticker":
        markets = request.url.params["markets"].split(",")
        return httpx.Response(
            200,
            json=[
                {"market": market, "trade_price": 100.0, "acc_trade_price_24h": 1_000_000.0}
                for market in markets
            ],
        )
    if path.startswith("/v1/candles/minutes/"):
        market = request.url.params["market"]
        return httpx.Response(200, json=_upbit_candles_json(_CANDLES_BY_MARKET[market], market))
    raise AssertionError(f"unexpected request path: {path}")


def _rest_client() -> UpbitRestClient:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler), base_url="https://mock.upbit.test")
    return UpbitRestClient(client)


@pytest.mark.asyncio
async def test_scan_returns_recommendations_only_for_eligible_breakout_candidates() -> None:
    recs = await scan_crypto_market(_rest_client(), account_buying_power=10_000_000.0)

    symbols = [r.symbol for r in recs]
    assert "KRW-AAA" in symbols
    assert "KRW-CCC" in symbols
    assert "KRW-BBB" not in symbols  # flat market never breaks out - never padded in


@pytest.mark.asyncio
async def test_scan_ranks_the_stronger_breakout_first() -> None:
    recs = await scan_crypto_market(_rest_client(), account_buying_power=10_000_000.0)

    symbols = [r.symbol for r in recs]
    assert symbols.index("KRW-AAA") < symbols.index("KRW-CCC")


@pytest.mark.asyncio
async def test_scan_uses_the_correctly_reversed_latest_bar_as_entry_price() -> None:
    """AAA's most-recent chronological close is 105.5 - if the reversal in
    crypto_scan._chronological() were wrong or missing, this would instead
    pick up the *oldest* bar's price (97.0)."""
    recs = await scan_crypto_market(_rest_client(), account_buying_power=10_000_000.0)

    aaa = next(r for r in recs if r.symbol == "KRW-AAA")
    assert aaa.entry_low == pytest.approx(105.5)
    assert aaa.stop_price == pytest.approx(95.0)  # opening-range low


@pytest.mark.asyncio
async def test_scan_respects_top_n_and_keeps_the_highest_scored() -> None:
    recs = await scan_crypto_market(_rest_client(), account_buying_power=10_000_000.0, top_n=1)

    assert len(recs) == 1
    assert recs[0].symbol == "KRW-AAA"


@pytest.mark.asyncio
async def test_scan_returns_empty_list_for_an_empty_universe() -> None:
    def empty_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/market/all"
        return httpx.Response(200, json=[])

    client = httpx.AsyncClient(transport=httpx.MockTransport(empty_handler), base_url="https://mock.upbit.test")
    rest = UpbitRestClient(client)

    assert await scan_crypto_market(rest, account_buying_power=10_000_000.0) == []
