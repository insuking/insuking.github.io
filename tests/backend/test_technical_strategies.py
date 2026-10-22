from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import Candle
from app.technical.strategies import StrategySignal, breakout_strategy, vwap_strategy

pytestmark = pytest.mark.P10


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


# --- vwap_strategy -----------------------------------------------------


def test_vwap_strategy_long_when_close_above_vwap() -> None:
    # A rising series where every close after the first bar sits above the
    # cumulative VWAP (VWAP lags a steady uptrend).
    candles = [_candle(close=100.0 + i, volume=10, minute=i) for i in range(10)]
    signals = vwap_strategy(candles)
    assert signals[0] == StrategySignal.FLAT  # close == vwap on the very first bar
    assert all(s == StrategySignal.LONG for s in signals[1:])


def test_vwap_strategy_short_when_close_below_vwap() -> None:
    candles = [_candle(close=100.0 - i, volume=10, minute=i) for i in range(10)]
    signals = vwap_strategy(candles)
    assert signals[0] == StrategySignal.FLAT
    assert all(s == StrategySignal.SHORT for s in signals[1:])


# --- breakout_strategy ---------------------------------------------------


def test_breakout_strategy_long_above_opening_range_high() -> None:
    # Opening range (first 3 bars) has high=101, low=99. A later close above
    # 101 should read LONG; a close inside the range should read FLAT.
    opening = [
        _candle(close=100, high=101, low=99, minute=0),
        _candle(close=100, high=100, low=99, minute=1),
        _candle(close=100, high=100, low=100, minute=2),
    ]
    inside = _candle(close=100, high=100, low=100, minute=3)
    breakout = _candle(close=105, high=105, low=105, minute=4)
    candles = [*opening, inside, breakout]

    signals = breakout_strategy(candles, opening_bars=3)

    assert signals[3] == StrategySignal.FLAT
    assert signals[4] == StrategySignal.LONG


def test_breakout_strategy_short_below_opening_range_low() -> None:
    opening = [
        _candle(close=100, high=101, low=99, minute=0),
        _candle(close=100, high=100, low=99, minute=1),
        _candle(close=100, high=100, low=100, minute=2),
    ]
    breakdown = _candle(close=95, high=95, low=95, minute=3)
    candles = [*opening, breakdown]

    signals = breakout_strategy(candles, opening_bars=3)

    assert signals[3] == StrategySignal.SHORT


def test_breakout_strategy_empty_candles_returns_empty() -> None:
    assert breakout_strategy([], opening_bars=5) == []
