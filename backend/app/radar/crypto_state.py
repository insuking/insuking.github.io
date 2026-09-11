"""Crypto radar state tracker (P9): hysteresis + pump-risk override.

Wraps P4's stateless `next_state()` with two things a 24/7 crypto feed
specifically needs that a session-bound stock radar didn't:

- **Hysteresis.** `next_state()` alone re-derives a state from a single
  bar's signals, so a borderline reading (rvol hovering right at the
  accumulation threshold) can flap the state back and forth every bar. This
  tracker requires a *candidate* transition to repeat for `confirm_bars`
  consecutive updates before it actually commits.
- **Pump-risk override**, from P8's `pump_risk_score`: crypto's pump-and-dump
  risk has no stock equivalent, so it isn't part of `next_state()`'s
  transition table at all - it's an overlay applied here.

Both safety-relevant transitions - into `PUMP_RISK` and into
`FAILED_BREAKOUT` - bypass the hysteresis delay and commit immediately.
Per docs/MASTER_SPEC.md's priority order ("1. Position Protection" before
everything else), smoothing out noise must never come at the cost of
delaying a risk-escalating signal - only state-advancing transitions
(accumulation, breakout, confirmation, re-entry) get the confirmation delay.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.radar.state import DEFAULT_THRESHOLDS, RadarState, StateThresholds, next_state

DEFAULT_CONFIRM_BARS = 2
DEFAULT_PUMP_RISK_THRESHOLD = 80.0

_IMMEDIATE_STATES = (RadarState.FAILED_BREAKOUT, RadarState.PUMP_RISK)


@dataclass
class CryptoRadarStateTracker:
    confirm_bars: int = DEFAULT_CONFIRM_BARS
    pump_risk_threshold: float = DEFAULT_PUMP_RISK_THRESHOLD
    thresholds: StateThresholds = field(default_factory=lambda: DEFAULT_THRESHOLDS)

    state: RadarState = field(default=RadarState.STEALTH, init=False)
    _pending_state: RadarState | None = field(default=None, init=False, repr=False)
    _pending_count: int = field(default=0, init=False, repr=False)

    def update(self, price: float, breakout_level: float, rvol: float, clv: float, pump_risk: float) -> RadarState:
        """Feed one bar's signals, returning the (possibly unchanged) committed state."""
        if pump_risk >= self.pump_risk_threshold:
            self._commit(RadarState.PUMP_RISK)
            return self.state

        candidate = next_state(self.state, price, breakout_level, rvol, clv, self.thresholds)

        if candidate == self.state:
            self._clear_pending()
            return self.state

        if candidate in _IMMEDIATE_STATES:
            self._commit(candidate)
            return self.state

        if candidate == self._pending_state:
            self._pending_count += 1
        else:
            self._pending_state = candidate
            self._pending_count = 1

        if self._pending_count >= self.confirm_bars:
            self._commit(candidate)

        return self.state

    def _commit(self, new_state: RadarState) -> None:
        self.state = new_state
        self._clear_pending()

    def _clear_pending(self) -> None:
        self._pending_state = None
        self._pending_count = 0
