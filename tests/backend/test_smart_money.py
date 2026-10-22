from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import Candle
from app.radar.smart_money import (
    absorption_score,
    buy_aggression_ratio,
    is_low_volume_pullback,
    support_defense_count,
    volume_compression_score,
)

pytestmark = pytest.mark.P11


def _candle(
    close: float,
    high: float | None = None,
    low: float | None = None,
    volume: float = 10,
    minute: int = 0,
) -> Candle:
    start = datetime(2026, 1, 5, tzinfo=UTC) + timedelta(minutes=minute)
    h = high if high is not None else close
    lo = low if low is not None else close
    return Candle(
        symbol="TEST",
        interval="1m",
        open=close,
        high=h,
        low=lo,
        close=close,
        volume=volume,
        open_time=start,
        close_time=start + timedelta(minutes=1),
    )


# --- absorption_score ----------------------------------------------------


def test_absorption_score_high_volume_small_range() -> None:
    baseline = [_candle(close=100, high=101, low=99, volume=10, minute=i) for i in range(5)]
    latest = _candle(close=100, high=100.25, low=99.75, volume=20, minute=5)
    candles = [*baseline, latest]

    score = absorption_score(candles, window=5)

    # relative_volume = 20/10 = 2.0 -> volume_component = min((2-1)*40, 60) = 40
    # relative_range = 0.5/2 = 0.25 -> range_component = min((1-0.25)*40, 40) = 30
    assert score == pytest.approx(70.0)


def test_absorption_score_none_without_full_window() -> None:
    candles = [_candle(close=100, minute=i) for i in range(4)]
    assert absorption_score(candles, window=5) is None


# --- support_defense_count -------------------------------------------------


def test_support_defense_count_counts_only_holds_within_tolerance() -> None:
    level = 100.0
    candles = [
        _candle(close=101, high=101, low=99.5, minute=0),  # dips in tolerance, closes above: defended
        _candle(close=101, high=101, low=98.5, minute=1),  # dips below tolerance: not counted
        _candle(close=99.5, high=100, low=99.5, minute=2),  # closes below level: not counted
        _candle(close=100.5, high=101, low=99.0, minute=3),  # dips exactly to threshold, closes above
    ]
    assert support_defense_count(candles, level=level, tolerance=0.01) == 2


def test_support_defense_count_zero_for_nonpositive_level() -> None:
    candles = [_candle(close=100, minute=0)]
    assert support_defense_count(candles, level=0.0) == 0


# --- is_low_volume_pullback -------------------------------------------------


def test_low_volume_pullback_true_when_declining_on_light_volume() -> None:
    prior = [_candle(close=100 + i, volume=20, minute=i) for i in range(5)]  # 100..104, up-move
    pullback = [
        _candle(close=103, volume=5, minute=5),
        _candle(close=102, volume=5, minute=6),
        _candle(close=101, volume=5, minute=7),
    ]
    assert is_low_volume_pullback(prior + pullback, pullback_bars=3, lookback_bars=5) is True


def test_low_volume_pullback_false_when_volume_expands() -> None:
    prior = [_candle(close=100 + i, volume=20, minute=i) for i in range(5)]
    pullback = [
        _candle(close=103, volume=30, minute=5),
        _candle(close=102, volume=30, minute=6),
        _candle(close=101, volume=30, minute=7),
    ]
    assert is_low_volume_pullback(prior + pullback, pullback_bars=3, lookback_bars=5) is False


def test_low_volume_pullback_false_when_not_declining() -> None:
    prior = [_candle(close=100 + i, volume=20, minute=i) for i in range(5)]
    not_a_pullback = [
        _candle(close=105, volume=5, minute=5),
        _candle(close=106, volume=5, minute=6),
        _candle(close=107, volume=5, minute=7),
    ]
    assert is_low_volume_pullback(prior + not_a_pullback, pullback_bars=3, lookback_bars=5) is False


# --- buy_aggression_ratio ---------------------------------------------------


def test_buy_aggression_ratio_volume_weighted_clv() -> None:
    candles = [
        _candle(close=100, high=110, low=90, volume=10, minute=0),  # CLV = 0
        _candle(close=105, high=110, low=90, volume=30, minute=1),  # CLV = 0.5
    ]
    # weighted = (0*10 + 0.5*30) / 40 = 0.375
    assert buy_aggression_ratio(candles, window=10) == pytest.approx(0.375)


def test_buy_aggression_ratio_zero_for_empty_candles() -> None:
    assert buy_aggression_ratio([], window=10) == 0.0


# --- volume_compression_score -----------------------------------------------


def test_volume_compression_score_detects_contraction() -> None:
    baseline = [_candle(close=100, high=102, low=98, volume=20, minute=i) for i in range(5)]
    recent = [_candle(close=100, high=101, low=99, volume=10, minute=5 + i) for i in range(5)]
    candles = baseline + recent

    score = volume_compression_score(candles, short_window=5, long_window=10)

    # volume_ratio = 10/20 = 0.5, range_ratio = 2/4 = 0.5 -> compression = 1 - 0.5 = 0.5
    assert score == pytest.approx(0.5)


def test_volume_compression_score_none_without_full_long_window() -> None:
    candles = [_candle(close=100, minute=i) for i in range(9)]
    assert volume_compression_score(candles, short_window=5, long_window=10) is None


def test_volume_compression_score_rejects_bad_window_ordering() -> None:
    candles = [_candle(close=100, minute=i) for i in range(10)]
    with pytest.raises(ValueError, match="short_window"):
        volume_compression_score(candles, short_window=10, long_window=10)
