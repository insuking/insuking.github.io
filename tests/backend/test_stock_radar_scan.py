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
from app.radar.regime import MarketRegime
from app.stock_radar.entry_confirmation import EntryConfirmation, EntryVerdict
from app.stock_radar.scan import (
    build_confirmed_recommendations,
    rank_prebreakout_candidates,
    reconfirm_candidates,
    scan_stock_universe,
)
from app.stock_radar.scoring import (
    SCORE_MAX_AVAILABLE,
    SCORE_MAX_WITH_INSTITUTIONAL_FLOW,
    PreBreakoutScore,
)

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
    names_by_symbol = {"005930": "삼성전자", "000660": "SK하이닉스"}

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
            return httpx.Response(
                200,
                json={
                    "rt_cd": "0",
                    "output1": {"hts_kor_isnm": names_by_symbol[symbol]},
                    "output2": list(reversed(output2)),
                },
            )
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-investor":
            return httpx.Response(
                200,
                json={
                    "rt_cd": "0",
                    "output": [
                        {"stck_bsop_date": (_START + timedelta(days=i)).strftime("%Y%m%d"), "frgn_ntby_qty": "100", "orgn_ntby_qty": "50"}
                        for i in range(10)
                    ],
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=settings))

    results, names = await scan_stock_universe(
        rest,
        symbols=["005930", "000660"],
        benchmark_candles=_flat_benchmark(75),
        start_date="20260101",
        end_date="20260314",
    )

    assert [r.symbol for r in results] == ["005930", "000660"]
    assert results[0].total_score > results[1].total_score
    assert names == {"005930": "삼성전자", "000660": "SK하이닉스"}
    # investor-flow data was fetched and fed into scoring (P25) - ceiling
    # includes institutional_flow, not just the price/volume factors.
    assert results[0].max_available == pytest.approx(SCORE_MAX_WITH_INSTITUTIONAL_FLOW)


@pytest.mark.asyncio
async def test_scan_stock_universe_degrades_gracefully_when_investor_trend_fails() -> None:
    """`get_investor_trend()`'s field layout isn't independently verified
    yet (see rest_client.py's module docstring) - a real KIS error there
    must not crash the whole scan, since price/volume scoring (P23) is
    already known-good. Coverage for the try/except in scan_stock_universe()."""
    settings = Settings(kis_app_key="test-key", kis_app_secret="test-secret")  # type: ignore[call-arg]
    bars = _textbook_setup_bars()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice":
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
            return httpx.Response(
                200, json={"rt_cd": "0", "output1": {}, "output2": list(reversed(output2))}
            )
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-investor":
            # Simulates a real KIS rejection (e.g. an unverified field/param mismatch).
            return httpx.Response(200, json={"rt_cd": "1", "msg1": "조회 실패", "output": []})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=settings))

    results, _names = await scan_stock_universe(
        rest,
        symbols=["005930"],
        benchmark_candles=_flat_benchmark(75),
        start_date="20260101",
        end_date="20260314",
    )

    assert len(results) == 1
    assert results[0].max_available == pytest.approx(SCORE_MAX_AVAILABLE)


@pytest.mark.P27
@pytest.mark.asyncio
async def test_reconfirm_candidates_fetches_a_fresh_quote_per_symbol() -> None:
    settings = Settings(kis_app_key="test-key", kis_app_secret="test-secret")  # type: ignore[call-arg]
    quotes_by_symbol = {"005930": "103000", "000660": "94000"}  # 005930 gapped up 3%, 000660 gapped down 6%

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-price":
            symbol = request.url.params["FID_INPUT_ISCD"]
            return httpx.Response(
                200, json={"rt_cd": "0", "output": {"stck_prpr": quotes_by_symbol[symbol], "acml_vol": "1000"}}
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=settings))
    results = [
        PreBreakoutScore(symbol="005930", total_score=40.0, max_available=65.0, reference_close=100000.0),
        PreBreakoutScore(symbol="000660", total_score=30.0, max_available=65.0, reference_close=100000.0),
    ]

    confirmations = await reconfirm_candidates(rest, results, regime=MarketRegime.RISK_ON)

    by_symbol = {c.symbol: c for c in confirmations}
    assert by_symbol["005930"].verdict == EntryVerdict.CONFIRMED
    assert by_symbol["000660"].verdict == EntryVerdict.REJECTED
    assert by_symbol["000660"].gap_pct == pytest.approx(-6.0)


@pytest.mark.P27
@pytest.mark.asyncio
async def test_reconfirm_candidates_rejects_a_symbol_whose_quote_fetch_fails_without_crashing() -> None:
    settings = Settings(kis_app_key="test-key", kis_app_secret="test-secret")  # type: ignore[call-arg]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-price":
            return httpx.Response(200, json={"rt_cd": "1", "msg1": "조회 실패", "output": {}})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=settings))
    results = [PreBreakoutScore(symbol="005930", total_score=40.0, max_available=65.0, reference_close=100000.0)]

    confirmations = await reconfirm_candidates(rest, results, regime=MarketRegime.RISK_ON)

    assert len(confirmations) == 1
    assert confirmations[0].verdict == EntryVerdict.REJECTED
    assert confirmations[0].reasons


def _daily_price_response(count: int, base: float = 100000.0) -> dict:
    rows = []
    for i in range(count):
        date = (_START + timedelta(days=i)).strftime("%Y%m%d")
        close = base + i * 100
        rows.append(
            {
                "stck_bsop_date": date,
                "stck_oprc": str(close),
                "stck_hgpr": str(close + 1000),
                "stck_lwpr": str(close - 1000),
                "stck_clpr": str(close),
                "acml_vol": "10000",
            }
        )
    return {"rt_cd": "0", "output1": {}, "output2": rows}


@pytest.mark.P31
@pytest.mark.asyncio
async def test_build_confirmed_recommendations_creates_one_per_confirmed_symbol() -> None:
    settings = Settings(kis_app_key="test-key", kis_app_secret="test-secret")  # type: ignore[call-arg]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice":
            return httpx.Response(200, json=_daily_price_response(20))
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=settings))

    scores = [
        PreBreakoutScore(symbol="005930", total_score=40.0, max_available=65.0, reference_close=100000.0),
        PreBreakoutScore(symbol="000660", total_score=30.0, max_available=65.0, reference_close=100000.0),
    ]
    confirmations = [
        EntryConfirmation(symbol="005930", verdict=EntryVerdict.CONFIRMED, gap_pct=1.0, current_price=101000.0),
        EntryConfirmation(symbol="000660", verdict=EntryVerdict.REJECTED, gap_pct=6.0, current_price=106000.0),
    ]

    recommendations = await build_confirmed_recommendations(
        rest, scores, confirmations, account_buying_power=10_000_000.0, start_date="20260101", end_date="20260201"
    )

    assert len(recommendations) == 1
    assert recommendations[0].symbol == "005930"
    assert recommendations[0].entry_low == pytest.approx(101000.0)
    assert recommendations[0].name is None  # no `names` dict passed - never fabricated


@pytest.mark.P33
@pytest.mark.asyncio
async def test_build_confirmed_recommendations_carries_names_through_when_given() -> None:
    settings = Settings(kis_app_key="test-key", kis_app_secret="test-secret")  # type: ignore[call-arg]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice":
            return httpx.Response(200, json=_daily_price_response(20))
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=settings))

    scores = [PreBreakoutScore(symbol="005930", total_score=40.0, max_available=65.0, reference_close=100000.0)]
    confirmations = [
        EntryConfirmation(symbol="005930", verdict=EntryVerdict.CONFIRMED, gap_pct=1.0, current_price=101000.0)
    ]

    recommendations = await build_confirmed_recommendations(
        rest,
        scores,
        confirmations,
        account_buying_power=10_000_000.0,
        start_date="20260101",
        end_date="20260201",
        names={"005930": "삼성전자"},
    )

    assert len(recommendations) == 1
    assert recommendations[0].name == "삼성전자"


@pytest.mark.P31
@pytest.mark.asyncio
async def test_build_confirmed_recommendations_skips_symbol_on_candle_fetch_failure() -> None:
    settings = Settings(kis_app_key="test-key", kis_app_secret="test-secret")  # type: ignore[call-arg]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice":
            return httpx.Response(200, json={"rt_cd": "1", "msg1": "조회 실패"})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=settings))

    scores = [PreBreakoutScore(symbol="005930", total_score=40.0, max_available=65.0, reference_close=100000.0)]
    confirmations = [
        EntryConfirmation(symbol="005930", verdict=EntryVerdict.CONFIRMED, gap_pct=1.0, current_price=101000.0)
    ]

    recommendations = await build_confirmed_recommendations(
        rest, scores, confirmations, account_buying_power=10_000_000.0, start_date="20260101", end_date="20260201"
    )

    assert recommendations == []
