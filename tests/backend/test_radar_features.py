from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import Candle
from app.radar.features import (
    close_location_value,
    compression_score,
    distance_to_high,
    liquidity_score,
    obv,
    obv_slope,
    opening_range,
    relative_strength,
    relative_volume,
    turnover,
    turnover_acceleration,
    vwap,
    vwap_series,
)

pytestmark = pytest.mark.P4


def _candle(open_, high, low, close, volume, minute: int = 0) -> Candle:
    start = datetime(2026, 1, 5, 9, minute, tzinfo=UTC)
    return Candle(
        symbol="TEST",
        interval="1m",
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        open_time=start,
        close_time=start + timedelta(minutes=1),
    )


def test_vwap_series_matches_hand_calculation() -> None:
    candles = [
        _candle(100, 102, 98, 100, 10, minute=0),  # typical = 100
        _candle(100, 106, 100, 104, 30, minute=1),  # typical = 103.333...
    ]

    series = vwap_series(candles)

    assert series[0] == pytest.approx(100.0)
    expected_second = (100 * 10 + (106 + 100 + 104) / 3 * 30) / 40
    assert series[1] == pytest.approx(expected_second)
    assert vwap(candles) == pytest.approx(expected_second)


def test_vwap_raises_on_empty_input() -> None:
    with pytest.raises(ValueError, match="at least one candle"):
        vwap([])


def test_relative_volume_ratio() -> None:
    assert relative_volume(current_volume=300, average_volume=100) == pytest.approx(3.0)
    assert relative_volume(current_volume=50, average_volume=0) == 0.0


def test_turnover_is_price_times_volume() -> None:
    assert turnover(_candle(100, 100, 100, 100, 5)) == pytest.approx(500.0)


def test_turnover_acceleration_detects_rising_money_flow() -> None:
    quiet = [_candle(100, 100, 100, 100, 10, minute=i) for i in range(5)]
    busy = [_candle(100, 100, 100, 100, 100, minute=5 + i) for i in range(5)]

    accel = turnover_acceleration(quiet + busy, window=5)

    assert accel == pytest.approx(9.0)  # avg turnover 10000 vs 1000 -> (10000-1000)/1000


def test_turnover_acceleration_needs_two_full_windows() -> None:
    candles = [_candle(100, 100, 100, 100, 10, minute=i) for i in range(5)]
    assert turnover_acceleration(candles, window=5) == 0.0


def test_opening_range_uses_first_n_bars() -> None:
    candles = [
        _candle(100, 110, 95, 105, 10, minute=0),
        _candle(105, 108, 100, 102, 10, minute=1),
        _candle(102, 200, 50, 150, 10, minute=2),  # outside the opening window
    ]

    orange = opening_range(candles, bars=2)

    assert orange.high == 110
    assert orange.low == 95


def test_close_location_value_extremes_and_midpoint() -> None:
    assert close_location_value(_candle(100, 110, 100, 110, 10)) == pytest.approx(1.0)
    assert close_location_value(_candle(100, 110, 100, 100, 10)) == pytest.approx(-1.0)
    assert close_location_value(_candle(100, 110, 100, 105, 10)) == pytest.approx(0.0)
    assert close_location_value(_candle(100, 100, 100, 100, 10)) == 0.0  # zero range


def test_relative_strength_outperformance() -> None:
    stock = [_candle(100, 100, 100, 100, 1, minute=0), _candle(100, 100, 100, 110, 1, minute=1)]
    benchmark = [_candle(100, 100, 100, 100, 1, minute=0), _candle(100, 100, 100, 104, 1, minute=1)]

    rs = relative_strength(stock, benchmark)

    assert rs == pytest.approx(0.06)


def test_relative_strength_requires_two_candles() -> None:
    with pytest.raises(ValueError, match="at least 2 candles"):
        relative_strength([_candle(100, 100, 100, 100, 1)], [_candle(100, 100, 100, 100, 1)])


def test_liquidity_score_is_average_turnover() -> None:
    candles = [_candle(100, 100, 100, 100, 10, minute=0), _candle(100, 100, 100, 200, 20, minute=1)]
    assert liquidity_score(candles) == pytest.approx((1000 + 4000) / 2)


def test_liquidity_score_empty_is_zero() -> None:
    assert liquidity_score([]) == 0.0


# --- P23: compression / OBV / distance-to-high --------------------------


@pytest.mark.P23
def test_obv_accumulates_on_up_closes_and_subtracts_on_down_closes() -> None:
    candles = [
        _candle(100, 100, 100, 100, 1, minute=0),
        _candle(100, 100, 100, 105, 10, minute=1),  # up close: +10
        _candle(100, 100, 100, 102, 5, minute=2),  # down close: -5
        _candle(100, 100, 100, 102, 3, minute=3),  # flat close: unchanged
    ]

    assert obv(candles) == [0.0, 10.0, 5.0, 5.0]


@pytest.mark.P23
def test_obv_slope_is_none_without_enough_history() -> None:
    candles = [_candle(100, 100, 100, 100, 1, minute=i) for i in range(5)]
    assert obv_slope(candles, window=10) is None


@pytest.mark.P23
def test_obv_slope_is_positive_when_recent_bars_are_net_buying() -> None:
    candles = [_candle(100, 100, 100, 100 + i, 10, minute=i) for i in range(11)]  # steadily rising closes
    slope = obv_slope(candles, window=10)
    assert slope is not None
    assert slope > 0


@pytest.mark.P23
def test_distance_to_high_is_zero_at_the_window_high() -> None:
    candles = [_candle(100, 105, 95, 100, 10, minute=i) for i in range(19)]
    candles.append(_candle(100, 110, 100, 110, 10, minute=19))  # new high, closes at it

    assert distance_to_high(candles, window=20) == pytest.approx(0.0)


@pytest.mark.P23
def test_distance_to_high_is_positive_below_the_window_high() -> None:
    candles = [_candle(100, 110, 95, 100, 10, minute=i) for i in range(20)]
    candles[-1] = _candle(95, 100, 90, 95, 10, minute=19)  # closes well below the 110 high

    assert distance_to_high(candles, window=20) == pytest.approx((110 - 95) / 110)


@pytest.mark.P23
def test_distance_to_high_is_none_without_enough_history() -> None:
    assert distance_to_high([_candle(100, 100, 100, 100, 1)], window=20) is None


@pytest.mark.P23
def test_compression_score_is_none_without_enough_history() -> None:
    assert compression_score([_candle(100, 100, 100, 100, 1)], window=20, lookback=60) is None


@pytest.mark.P23
def test_compression_score_ranks_a_currently_narrow_band_higher() -> None:
    oscillating = [
        _candle(100, 115, 85, 100 if i % 2 == 0 else 110, 10, minute=i) for i in range(15)
    ]
    flat = [_candle(105, 106, 104, 105, 10, minute=15 + i) for i in range(5)]
    candles = oscillating + flat

    score = compression_score(candles, window=5, lookback=15)

    assert score is not None
    assert score > 0.8  # the flat tail's band width is narrower than nearly all of the oscillating history
