"""P23: stock radar scan orchestration.

`rank_prebreakout_candidates()` is pure and gets most of the coverage;
`scan_stock_universe()` gets one mocked-KIS test proving the wiring
(fetch -> pure rank) works end to end, matching test_crypto_scan.py's
split between "verify the wiring" and "verify the pure logic" for the
crypto side.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import Settings
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.rest_client import KisRestClient
from app.models.domain import Candle
from app.stock_radar.scan import rank_prebreakout_candidates, scan_stock_universe

pytestmark = pytest.mark.P23

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(open_: float, high: float, low: float, close: float, volume: float) -> tuple:
    return (open_, high, low, close, volume)


def _to_candles(bars: list[tuple], symbol: str) -> list[Candle]:
    candles = []
    for i, (open_, high, low, close, volume) in enumerate(bars):
        open_time = _START + timedelta(days=i)
        candles.append(
            Candle(
                symbol=symbol,
                interval="1d",
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                open_time=open_time,
                close_time=open_time + timedelta(days=1),
            )
        )
    return candles


def _flat_benchmark(length: int) -> list[Candle]:
    return _to_candles([_bar(1000.0, 1005.0, 995.0, 1000.0, 1_000_000.0) for _ in range(length)], "KOSPI")


def _textbook_setup_bars() -> list[tuple]:
    baseline = [_bar(100.0, 106.0, 94.0, 100.0 if i % 2 == 0 else 103.0, 1_000_000.0) for i in range(70)]
    tail = [
        _bar(103.0, 104.5, 102.5, 103.5, 1_000_000.0),
        _bar(103.5, 104.8, 103.0, 104.0, 1_050_000.0),
        _bar(104.0, 105.0, 103.5, 104.3, 1_100_000.0),
        _bar(104.3, 105.2, 103.8, 104.6, 1_500_000.0),
        _bar(104.6, 105.4, 104.0, 105.0, 2_200_000.0),
    ]
    return baseline + tail


def _flat_bars(count: int = 75) -> list[tuple]:
    return [_bar(100.0, 101.0, 99.0, 100.0, 1_000_000.0) for _ in range(count)]


def test_ranks_a_strong_setup_above_a_flat_one_and_respects_top_n() -> None:
    symbol_candles = {
        "STRONG": _to_candles(_textbook_setup_bars(), "STRONG"),
        "FLAT": _to_candles(_flat_bars(), "FLAT"),
        "TOO_SHORT": _to_candles(_flat_bars(count=10), "TOO_SHORT"),
    }

    results = rank_prebreakout_candidates(symbol_candles, _flat_benchmark(75), top_n=1)

    assert len(results) == 1
    assert results[0].symbol == "STRONG"


def test_skips_symbols_without_enough_history_rather_than_scoring_them() -> None:
    symbol_candles = {"TOO_SHORT": _to_candles(_flat_bars(count=10), "TOO_SHORT")}

    results = rank_prebreakout_candidates(symbol_candles, _flat_benchmark(75))

    assert results == []


@pytest.mark.asyncio
async def test_scan_stock_universe_fetches_real_prices_and_ranks_them() -> None:
    settings = Settings(kis_app_key="test-key", kis_app_secret="test-secret")  # type: ignore[call-arg]
    bars_by_symbol = {
        "005930": _textbook_setup_bars(),
        "000660": _flat_bars(),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice":
            symbol = request.url.params["FID_INPUT_ISCD"]
            bars = bars_by_symbol[symbol]
            output2 = [
                {
                    "stck_bsop_date": (_START + timedelta(days=i)).strftime("%Y%m%d"),
                    "stck_oprc": str(o),
                    "stck_hgpr": str(h),
                    "stck_lwpr": str(low),
                    "stck_clpr": str(c),
                    "acml_vol": str(v),
                }
                for i, (o, h, low, c, v) in enumerate(bars)
            ]
            # KIS convention (unverified - see rest_client.py): most-recent-first.
            return httpx.Response(200, json={"rt_cd": "0", "output1": {}, "output2": list(reversed(output2))})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=settings))

    results = await scan_stock_universe(
        rest,
        symbols=["005930", "000660"],
        benchmark_candles=_flat_benchmark(75),
        start_date="20260101",
        end_date="20260314",
    )

    assert [r.symbol for r in results] == ["005930", "000660"]
    assert results[0].total_score > results[1].total_score
