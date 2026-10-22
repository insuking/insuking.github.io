"""Dynamic trailing stop (P16).

Per docs/MASTER_SPEC.md section G-J: "the remaining runner position uses
dynamic trailing (ATR, realized volatility, VWAP, EMA, recent swing low,
orderflow, distribution risk, high giveback) that only tightens, never
loosens." This implements the ATR half of that list - a well-understood,
directly testable volatility-adjusted trail - reusing P10's `atr()` rather
than recomputing true range. The other listed inputs (orderflow,
distribution risk, "high giveback") describe judgment calls a single pure
function can't responsibly fabricate without real order-flow data this
codebase doesn't have yet; ATR trailing is the honest, working slice today,
not a claim that every listed technique is implemented.

The "only tightens, never loosens" rule is enforced structurally: this
always returns `max(current_stop, candidate)` for a long position, so a
caller can apply the result unconditionally without its own comparison.
"""

from __future__ import annotations

from app.models.domain import Candle
from app.technical.indicators import atr


def trailing_stop_price(
    candles: list[Candle],
    current_stop: float,
    atr_multiplier: float = 2.0,
    atr_window: int = 14,
) -> float:
    """The tighter of `current_stop` and `latest_close - atr_multiplier * ATR`.

    Returns `current_stop` unchanged when there isn't enough history for a
    full ATR window yet - "not enough data" must never loosen a stop either.
    """
    if len(candles) < atr_window:
        return current_stop

    latest_atr = atr(candles, window=atr_window)[-1]
    if latest_atr is None:
        return current_stop

    candidate = candles[-1].close - atr_multiplier * latest_atr
    return max(current_stop, candidate)
