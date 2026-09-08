"""P23: PRE-BREAKOUT scoring engine.

Synthetic daily-candle fixtures (not real KIS data - real credentials
aren't provisioned yet, see docs/KIS_SETUP.md) built to isolate the
"textbook setup" (compressed, volume ramping, near its high, positive
relative strength) from a flat "nothing going on" baseline, and to prove
`total_score` never exceeds its own `max_available` denominator.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import Candle
from app.stock_radar.scoring import (
    SCORE_MAX_AVAILABLE,
    PreBreakoutWeights,
    score_prebreakout,
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


def _flat_benchmark(length: int, drift: float = 0.0) -> list[Candle]:
    bars = [_bar(1000.0 + i * drift, 1005.0 + i * drift, 995.0 + i * drift, 1000.0 + i * drift, 1_000_000.0) for i in range(length)]
    return _to_candles(bars, "KOSPI")


def _textbook_setup_candles() -> list[Candle]:
    # 70 days of mild oscillation (builds a normal ATR/Bollinger/volume baseline).
    baseline = [_bar(100.0, 106.0, 94.0, 100.0 if i % 2 == 0 else 103.0, 1_000_000.0) for i in range(70)]
    # Final 10 days: range tightens toward the 70-day high, volume ramps up, closes strong.
    tail = [
        _bar(103.0, 104.5, 102.5, 103.5, 1_000_000.0),
        _bar(103.5, 104.8, 103.0, 104.0, 1_050_000.0),
        _bar(104.0, 105.0, 103.5, 104.3, 1_100_000.0),
        _bar(104.3, 105.2, 103.8, 104.6, 1_500_000.0),
        _bar(104.6, 105.4, 104.0, 105.0, 2_200_000.0),
    ]
    return _to_candles(baseline + tail, "005930")


def _flat_no_signal_candles() -> list[Candle]:
    bars = [_bar(100.0, 101.0, 99.0, 100.0, 1_000_000.0) for _ in range(75)]
    return _to_candles(bars, "005930")


def test_returns_none_without_enough_history() -> None:
    candles = _to_candles([_bar(100.0, 101.0, 99.0, 100.0, 1000.0) for _ in range(10)], "005930")
    benchmark = _flat_benchmark(10)

    assert score_prebreakout("005930", candles, benchmark) is None


def test_textbook_setup_scores_well_above_a_flat_baseline() -> None:
    strong = score_prebreakout("005930", _textbook_setup_candles(), _flat_benchmark(75, drift=0.5))
    flat = score_prebreakout("005930", _flat_no_signal_candles(), _flat_benchmark(75))

    assert strong is not None
    assert flat is not None
    assert strong.total_score > flat.total_score
    assert len(strong.positive) >= 3


def test_score_never_exceeds_its_own_max_available() -> None:
    result = score_prebreakout("005930", _textbook_setup_candles(), _flat_benchmark(75, drift=0.5))

    assert result is not None
    assert result.max_available == pytest.approx(SCORE_MAX_AVAILABLE)
    assert 0.0 <= result.total_score <= result.max_available


def test_a_bar_that_sets_a_fresh_high_scores_full_distance_to_high_points() -> None:
    """distance_to_high() is always >= 0 for valid OHLC (the window
    includes the latest bar itself, whose own high can't be below its own
    close) - so the strongest case is distance == 0.0 (closed right at a
    fresh high), not a negative "already broken out" value. See
    app/radar/features.py's distance_to_high() docstring."""
    baseline = [_bar(100.0, 106.0, 94.0, 100.0, 1_000_000.0) for _ in range(74)]
    fresh_high_bar = [_bar(100.0, 130.0, 100.0, 130.0, 1_000_000.0)]  # closes exactly at its own new high
    candles = _to_candles(baseline + fresh_high_bar, "005930")

    result = score_prebreakout("005930", candles, _flat_benchmark(75))

    assert result is not None
    assert any(f.factor == "distance_to_high" for f in result.positive)


def test_custom_weights_change_the_total() -> None:
    candles = _textbook_setup_candles()
    benchmark = _flat_benchmark(75, drift=0.5)

    default_result = score_prebreakout("005930", candles, benchmark)
    zeroed = PreBreakoutWeights(
        compression=0.0,
        volume_increase=0.0,
        value_increase=0.0,
        distance_to_high=0.0,
        atr_structure=0.0,
        obv_rising=0.0,
        market_relative_strength=0.0,
    )
    zero_result = score_prebreakout("005930", candles, benchmark, weights=zeroed)

    assert default_result is not None
    assert zero_result is not None
    assert default_result.total_score > 0
    assert zero_result.total_score == 0.0
    assert zero_result.max_available == 0.0
