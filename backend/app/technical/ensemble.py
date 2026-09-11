"""Combine indicator/strategy signals into one technical score (P10).

This is read-only signal aggregation. Per docs/MASTER_SPEC.md P10 ("Technical
score must not directly order"): this module contains no order-placement
code, calls no execution client, and returns a plain data value - there is
no order-placement code anywhere in this codebase yet (that lands in P15,
downstream of the human-approval flow P13/P14 build first).

Four equal-weighted components, each normalized to [-100, 100] so no single
one dominates by construction:

- RSI, centered at 50 and scaled: `(rsi - 50) * 2`.
- MACD histogram sign: +100 / -100 / 0.
- VWAP strategy stance: +100 (LONG) / -100 (SHORT) / 0 (FLAT).
- Breakout strategy stance: same scale.

Returns `None` rather than a partial score when any component isn't defined
yet (not enough history) - a score built from 3 of 4 components would
misrepresent how much signal actually backs it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.domain import Candle
from app.technical.indicators import macd, rsi
from app.technical.strategies import StrategySignal, breakout_strategy, vwap_strategy

_SIGNAL_SCORE = {StrategySignal.LONG: 100.0, StrategySignal.FLAT: 0.0, StrategySignal.SHORT: -100.0}

# MACD's slow EMA needs 26 bars before it's defined at all, plus a handful
# more for the signal line's own smoothing to settle - short of that, don't
# even attempt a score.
MIN_CANDLES = 35


@dataclass
class EnsembleScore:
    score: float
    components: dict[str, float]


def ensemble_score(candles: list[Candle], opening_bars: int = 5) -> EnsembleScore | None:
    """Composite score for the latest bar, or None if history is insufficient."""
    if len(candles) < MIN_CANDLES:
        return None

    latest_rsi = rsi(candles)[-1]
    latest_macd = macd(candles)[-1]
    if latest_rsi is None or latest_macd is None:
        return None

    latest_vwap_signal = vwap_strategy(candles)[-1]
    latest_breakout_signal = breakout_strategy(candles, opening_bars=opening_bars)[-1]

    components = {
        "rsi": (latest_rsi - 50) * 2,
        "macd": 100.0 if latest_macd.histogram > 0 else (-100.0 if latest_macd.histogram < 0 else 0.0),
        "vwap_strategy": _SIGNAL_SCORE[latest_vwap_signal],
        "breakout_strategy": _SIGNAL_SCORE[latest_breakout_signal],
    }
    return EnsembleScore(score=sum(components.values()) / len(components), components=components)
