"""Strategy signal generation (P10).

Each strategy produces a per-bar directional lean (LONG/FLAT/SHORT) from the
indicators above or from P4's asset-agnostic feature functions - not an
order. See indicators.py's module docstring for why that boundary matters.
"""

from __future__ import annotations

from enum import Enum

from app.models.domain import Candle
from app.radar.features import opening_range, vwap_series


class StrategySignal(str, Enum):
    LONG = "LONG"
    FLAT = "FLAT"
    SHORT = "SHORT"


def vwap_strategy(candles: list[Candle]) -> list[StrategySignal]:
    """LONG while the close is above session VWAP, SHORT while below, FLAT at it."""
    vwaps = vwap_series(candles)
    signals = []
    for candle, vwap_value in zip(candles, vwaps):
        if candle.close > vwap_value:
            signals.append(StrategySignal.LONG)
        elif candle.close < vwap_value:
            signals.append(StrategySignal.SHORT)
        else:
            signals.append(StrategySignal.FLAT)
    return signals


def breakout_strategy(candles: list[Candle], opening_bars: int = 5) -> list[StrategySignal]:
    """LONG once the close is above the opening range high, SHORT below its
    low, FLAT inside it. The opening range is fixed from the first
    `opening_bars` bars for the whole series, same as P4's stock radar.
    """
    if not candles:
        return []
    session_range = opening_range(candles, bars=opening_bars)
    signals = []
    for candle in candles:
        if candle.close > session_range.high:
            signals.append(StrategySignal.LONG)
        elif candle.close < session_range.low:
            signals.append(StrategySignal.SHORT)
        else:
            signals.append(StrategySignal.FLAT)
    return signals
