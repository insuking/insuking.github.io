"""Market regime classification (P4).

A coarse read on "is the tape helping or fighting a breakout attempt", used
later to gate recommendations (P6) and to answer the home screen's "is the
market safe right now?" question (see docs/MASTER_SPEC.md, UX PRINCIPLES).
Deliberately simple: moving-average level and slope on the benchmark index,
not a claim of deep market microstructure analysis.
"""

from __future__ import annotations

from enum import Enum

from app.models.domain import Candle


class MarketRegime(str, Enum):
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    NEUTRAL = "NEUTRAL"


def classify_market_regime(index_candles: list[Candle], ma_window: int = 20) -> MarketRegime:
    """Classify a benchmark index series (e.g. KOSPI) by MA level and slope.

    RISK_ON: price above its moving average AND the average is rising.
    RISK_OFF: price below its moving average AND the average is falling.
    NEUTRAL: everything else (mixed/choppy signal) - the honest default when
    price and trend disagree, rather than forcing a call either way.
    """
    if len(index_candles) < ma_window + 1:
        return MarketRegime.NEUTRAL

    closes = [c.close for c in index_candles]
    ma_now = sum(closes[-ma_window:]) / ma_window
    ma_prev = sum(closes[-ma_window - 1 : -1]) / ma_window
    latest = closes[-1]

    above_ma = latest > ma_now
    rising_ma = ma_now > ma_prev

    if above_ma and rising_ma:
        return MarketRegime.RISK_ON
    if not above_ma and not rising_ma:
        return MarketRegime.RISK_OFF
    return MarketRegime.NEUTRAL
