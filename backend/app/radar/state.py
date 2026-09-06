"""Stock radar state machine (P4).

States mirror the crypto radar vocabulary docs/MASTER_SPEC.md defines in
full for P9, since the breakout lifecycle they describe (accumulate, break,
confirm, pull back or fail, distribute) is the same shape for either asset
class - P9 will reuse this enum and add the crypto-only PUMP_RISK state
rather than redefining the whole set.

`AVOID` is intentionally not reachable from `next_state()` here: it is set
by the risk engine (P18) overriding price-action signals entirely (e.g. a
halted stock, a data-integrity failure), not something derivable from a
single bar's price/volume/CLV - faking a price-based trigger for it here
would be exactly the kind of unverified behavior the master spec forbids.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RadarState(str, Enum):
    STEALTH = "STEALTH"
    ACCUMULATION = "ACCUMULATION"
    PRE_BREAKOUT = "PRE_BREAKOUT"
    BREAKOUT = "BREAKOUT"
    CONFIRMED_BREAKOUT = "CONFIRMED_BREAKOUT"
    PULLBACK = "PULLBACK"
    RE_ENTRY = "RE_ENTRY"
    DISTRIBUTION = "DISTRIBUTION"
    FAILED_BREAKOUT = "FAILED_BREAKOUT"
    AVOID = "AVOID"


@dataclass(frozen=True)
class StateThresholds:
    rvol_accumulation: float = 1.2
    rvol_breakout: float = 2.0
    pre_breakout_proximity: float = 0.995  # price / breakout_level
    clv_buying: float = 0.3
    clv_weak: float = -0.3


DEFAULT_THRESHOLDS = StateThresholds()


def next_state(
    prev_state: RadarState,
    price: float,
    breakout_level: float,
    rvol: float,
    clv: float,
    thresholds: StateThresholds = DEFAULT_THRESHOLDS,
) -> RadarState:
    """One deterministic transition step given the latest bar's signals.

    `breakout_level` is typically the session's opening-range high
    (see features.opening_range) - the level a close above/below is judged
    against for the entire session.
    """
    above_level = price >= breakout_level

    if above_level:
        if prev_state in (
            RadarState.STEALTH,
            RadarState.ACCUMULATION,
            RadarState.PRE_BREAKOUT,
            RadarState.FAILED_BREAKOUT,
        ):
            return RadarState.BREAKOUT

        if prev_state == RadarState.BREAKOUT:
            if clv <= thresholds.clv_weak:
                return RadarState.DISTRIBUTION
            if clv >= thresholds.clv_buying:
                return RadarState.CONFIRMED_BREAKOUT
            return RadarState.PULLBACK

        if prev_state in (RadarState.CONFIRMED_BREAKOUT, RadarState.PULLBACK, RadarState.RE_ENTRY):
            if clv <= thresholds.clv_weak:
                return RadarState.DISTRIBUTION
            if clv < thresholds.clv_buying:
                return RadarState.PULLBACK
            return RadarState.CONFIRMED_BREAKOUT

        if prev_state == RadarState.DISTRIBUTION:
            return RadarState.RE_ENTRY if clv >= thresholds.clv_buying else RadarState.DISTRIBUTION

        return RadarState.CONFIRMED_BREAKOUT  # AVOID or unexpected prior state: re-derive from price

    # price closed below the breakout level.
    if prev_state in (
        RadarState.BREAKOUT,
        RadarState.CONFIRMED_BREAKOUT,
        RadarState.PULLBACK,
        RadarState.DISTRIBUTION,
        RadarState.RE_ENTRY,
        RadarState.FAILED_BREAKOUT,
    ):
        return RadarState.FAILED_BREAKOUT

    proximity = price / breakout_level if breakout_level else 0.0
    if rvol >= thresholds.rvol_breakout and proximity >= thresholds.pre_breakout_proximity:
        return RadarState.PRE_BREAKOUT
    if rvol >= thresholds.rvol_accumulation and clv > 0:
        return RadarState.ACCUMULATION
    return RadarState.STEALTH
