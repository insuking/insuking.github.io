from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import Candle
from app.radar.psychology import (
    chasing_score,
    crowd_exhaustion_score,
    fomo_score,
    round_number_proximity,
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


# --- fomo_score --------------------------------------------------------


def test_fomo_score_matches_reference_calculation() -> None:
    prior = [
        _candle(close=100, volume=10, minute=0),
        _candle(close=101, volume=10, minute=1),
        _candle(close=102, volume=10, minute=2),
    ]
    recent = [
        _candle(close=102, volume=20, minute=3),
        _candle(close=105, volume=20, minute=4),
        _candle(close=110, volume=20, minute=5),
    ]
    candles = prior + recent

    result = fomo_score(candles, window=3)

    recent_return = (110 - 102) / 102
    prior_return = (102 - 100) / 100
    acceleration = recent_return - prior_return
    expected_score1 = max(0.0, min(acceleration * 200.0, 60.0))
    volume_expansion = 20 / 10
    expected_score2 = max(0.0, min((volume_expansion - 1.0) * 20.0, 40.0))
    expected = max(0.0, min(100.0, expected_score1 + expected_score2))

    assert result == pytest.approx(expected)


def test_fomo_score_zero_without_enough_history() -> None:
    candles = [_candle(close=100, minute=i) for i in range(4)]
    assert fomo_score(candles, window=3) == 0.0


# --- chasing_score -------------------------------------------------------


def test_chasing_score_combines_extension_and_aggression() -> None:
    candles = [
        _candle(close=100, high=110, low=90, volume=10, minute=0),  # CLV = 0
        _candle(close=105, high=110, low=90, volume=30, minute=1),  # CLV = 0.5
    ]
    # aggression = (0*10 + 0.5*30)/40 = 0.375
    # extension = (105-100)/100 = 0.05 -> min(5, 70) = 5
    # score = 5 + 0.375*30 = 16.25
    assert chasing_score(candles, breakout_level=100, window=10) == pytest.approx(16.25)


def test_chasing_score_zero_for_nonpositive_breakout_level() -> None:
    candles = [_candle(close=100, minute=0)]
    assert chasing_score(candles, breakout_level=0.0) == 0.0


def test_chasing_score_zero_for_empty_candles() -> None:
    assert chasing_score([], breakout_level=100.0) == 0.0


# --- round_number_proximity -------------------------------------------------


def test_round_number_proximity_exact_round_number() -> None:
    assert round_number_proximity(10000, step=1000) == pytest.approx(1.0)


def test_round_number_proximity_exact_midpoint() -> None:
    assert round_number_proximity(10500, step=1000) == pytest.approx(0.0)


def test_round_number_proximity_partial_distance() -> None:
    assert round_number_proximity(10250, step=1000) == pytest.approx(0.5)


def test_round_number_proximity_zero_for_invalid_input() -> None:
    assert round_number_proximity(0, step=1000) == 0.0
    assert round_number_proximity(100, step=0) == 0.0


# --- crowd_exhaustion_score -------------------------------------------------


def test_crowd_exhaustion_score_new_high_on_declining_volume() -> None:
    first_half = [_candle(close=100, high=100, volume=20, minute=i) for i in range(5)]
    second_half = [
        _candle(close=101 + i, high=101 + i, volume=10, minute=5 + i) for i in range(5)
    ]
    candles = first_half + second_half

    score = crowd_exhaustion_score(candles, window=10)

    # first_avg_volume=20, second_avg_volume=10 -> decline=(20-10)/20=0.5 -> 50.0
    assert score == pytest.approx(50.0)


def test_crowd_exhaustion_score_zero_when_not_a_new_high() -> None:
    candles = [_candle(close=100, high=200 if i == 3 else 100, volume=10, minute=i) for i in range(10)]
    assert crowd_exhaustion_score(candles, window=10) == 0.0


def test_crowd_exhaustion_score_zero_without_enough_history() -> None:
    candles = [_candle(close=100, minute=i) for i in range(5)]
    assert crowd_exhaustion_score(candles, window=10) == 0.0
