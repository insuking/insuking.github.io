from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import Candle
from app.stock_radar.overheat import HeatStatus, compute_heat_score

pytestmark = pytest.mark.P35


def _candle(close: float, day: int, high: float | None = None, low: float | None = None) -> Candle:
    start = datetime(2026, 1, 5, tzinfo=UTC) + timedelta(days=day)
    return Candle(
        symbol="005930",
        interval="1d",
        open=close,
        high=high if high is not None else close + 1,
        low=low if low is not None else close - 1,
        close=close,
        volume=1000,
        open_time=start,
        close_time=start + timedelta(days=1),
    )


def _flat_candles(count: int = 15, base: float = 100.0) -> list[Candle]:
    return [_candle(base, day=i) for i in range(count)]


def _candles_with_final_move(final_close: float, count: int = 15, base: float = 100.0) -> list[Candle]:
    """`count` flat bars at `base`, then the last bar replaced with
    `final_close` - isolates a single day's move so return_1d/2d/5d are
    all numerically equal (same numerator, same flat base), letting the
    smallest-threshold metric (return_1d, 8%) dominate the max-fraction
    calculation predictably."""
    candles = _flat_candles(count, base)
    candles[-1] = _candle(final_close, day=count - 1)
    return candles


def test_returns_none_with_insufficient_history() -> None:
    assert compute_heat_score(_flat_candles(count=10)) is None


def test_normal_status_for_a_quiet_flat_stock() -> None:
    result = compute_heat_score(_flat_candles())
    assert result is not None
    assert result.status == HeatStatus.NORMAL
    assert result.heat_score == pytest.approx(0.0)


def test_too_late_triggered_by_1day_return_threshold() -> None:
    # +8.5% in one day vs. an otherwise flat base - clears the 8% bar.
    result = compute_heat_score(_candles_with_final_move(108.5))
    assert result is not None
    assert result.return_1d_pct == pytest.approx(8.5)
    assert result.status == HeatStatus.TOO_LATE


def test_too_late_triggered_by_5day_return_threshold_even_when_1day_move_is_small() -> None:
    candles = _flat_candles(count=15)
    # A gradual 20% climb spread over the last 5 bars - no single day
    # crosses the 8% 1-day bar, but the 5-day accumulation clears 19%.
    for i, close in enumerate([104.0, 108.0, 112.0, 116.0, 120.0]):
        candles[-5 + i] = _candle(close, day=10 + i)

    result = compute_heat_score(candles)
    assert result is not None
    assert result.return_1d_pct < 8.0  # each individual day stays well under the 1-day TOO_LATE bar
    assert result.return_5d_pct == pytest.approx(20.0)
    assert result.status == HeatStatus.TOO_LATE


def test_a_large_decline_is_never_flagged_too_late() -> None:
    # Down 10% in a day is not "overheated" in this engine's sense -
    # negative fractions must never trip the OR gate.
    result = compute_heat_score(_candles_with_final_move(90.0))
    assert result is not None
    assert result.status != HeatStatus.TOO_LATE
    assert result.heat_score == pytest.approx(0.0)


def test_too_late_triggered_by_distance_from_signal() -> None:
    candles = _flat_candles(base=100.0)
    result = compute_heat_score(candles, entry_reference_price=90.0)  # +11.1% above the signal price
    assert result is not None
    assert result.distance_from_signal_pct == pytest.approx(11.111, rel=1e-3)
    assert result.status == HeatStatus.TOO_LATE


def test_distance_from_signal_is_none_without_a_reference_price() -> None:
    result = compute_heat_score(_flat_candles())
    assert result is not None
    assert result.distance_from_signal_pct is None


def test_too_late_triggered_by_an_excessive_gap() -> None:
    result = compute_heat_score(_flat_candles(), gap_pct=6.0, gap_allowed_pct=3.0)
    assert result is not None
    assert result.status == HeatStatus.TOO_LATE


def test_gap_is_none_without_a_confirmation() -> None:
    result = compute_heat_score(_flat_candles())
    assert result is not None
    assert result.gap_pct is None


@pytest.mark.parametrize(
    ("return_1d_target", "expected_status"),
    [
        (1.0, HeatStatus.NORMAL),
        (4.0, HeatStatus.WARM),
        (5.2, HeatStatus.HOT),
        (6.4, HeatStatus.VERY_HOT),
    ],
)
def test_heat_status_bands(return_1d_target: float, expected_status: HeatStatus) -> None:
    result = compute_heat_score(_candles_with_final_move(100.0 + return_1d_target))
    assert result is not None
    assert result.status == expected_status


def test_volume_bonus_pushes_heat_score_above_the_return_only_baseline() -> None:
    # 25 bars: enough for a full 20-bar volume baseline window plus the
    # 5-bar recent window on top, so the baseline is real (not an empty
    # window silently reading as 0 - see relative_volume()'s own doc).
    baseline = compute_heat_score(_flat_candles(count=25))
    assert baseline is not None
    assert baseline.heat_score == pytest.approx(0.0)

    candles = _flat_candles(count=25)
    # Recent 5 bars at 5x the (still-flat) prior baseline volume.
    for i in range(5):
        idx = len(candles) - 5 + i
        candles[idx] = Candle(
            symbol="005930",
            interval="1d",
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.0,
            volume=5000,
            open_time=candles[idx].open_time,
            close_time=candles[idx].close_time,
        )

    result = compute_heat_score(candles)
    assert result is not None
    assert result.volume_ratio > 2.0
    assert result.heat_score > baseline.heat_score
