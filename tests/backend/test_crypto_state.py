"""Crypto radar state tracker tests (P9): hysteresis + pump-risk override."""

import pytest

from app.radar.crypto_state import CryptoRadarStateTracker
from app.radar.state import RadarState, next_state

pytestmark = pytest.mark.P9


# --- boundary with P4 ----------------------------------------------------


def test_next_state_never_returns_pump_risk() -> None:
    """PUMP_RISK is crypto-only and only ever set by CryptoRadarStateTracker,
    never by P4's price-action transition function."""
    for state in RadarState:
        for price, level, rvol, clv in [
            (100, 100, 5.0, 0.9),
            (90, 100, 0.1, -0.9),
            (110, 100, 3.0, -0.9),
        ]:
            assert next_state(state, price, level, rvol, clv) != RadarState.PUMP_RISK


# --- hysteresis ------------------------------------------------------------


def test_borderline_flapping_signal_does_not_change_state() -> None:
    """Alternating between two candidate states bar-to-bar must never commit -
    that's exactly the chatter hysteresis exists to absorb."""
    tracker = CryptoRadarStateTracker(confirm_bars=3)

    for _ in range(10):
        tracker.update(price=98, breakout_level=100, rvol=1.3, clv=0.1, pump_risk=0.0)  # -> ACCUMULATION
        tracker.update(price=98, breakout_level=100, rvol=0.5, clv=-0.1, pump_risk=0.0)  # -> STEALTH

    assert tracker.state == RadarState.STEALTH  # never left the initial state


def test_sustained_signal_commits_after_confirm_bars() -> None:
    tracker = CryptoRadarStateTracker(confirm_bars=3)

    tracker.update(price=98, breakout_level=100, rvol=1.5, clv=0.5, pump_risk=0.0)
    assert tracker.state == RadarState.STEALTH  # 1st confirmation, not committed yet

    tracker.update(price=98, breakout_level=100, rvol=1.5, clv=0.5, pump_risk=0.0)
    assert tracker.state == RadarState.STEALTH  # 2nd confirmation, still pending

    tracker.update(price=98, breakout_level=100, rvol=1.5, clv=0.5, pump_risk=0.0)
    assert tracker.state == RadarState.ACCUMULATION  # 3rd confirmation - committed


def test_pending_confirmation_resets_if_candidate_changes() -> None:
    tracker = CryptoRadarStateTracker(confirm_bars=3)

    tracker.update(price=98, breakout_level=100, rvol=1.5, clv=0.5, pump_risk=0.0)  # candidate: ACCUMULATION
    tracker.update(price=98, breakout_level=100, rvol=1.5, clv=0.5, pump_risk=0.0)  # 2nd
    tracker.update(price=99.7, breakout_level=100, rvol=2.5, clv=0.5, pump_risk=0.0)  # candidate changes: PRE_BREAKOUT
    tracker.update(price=99.7, breakout_level=100, rvol=2.5, clv=0.5, pump_risk=0.0)  # 2nd for new candidate

    assert tracker.state == RadarState.STEALTH  # neither candidate reached 3 in a row


# --- immediate transitions: FAILED_BREAKOUT ------------------------------


def _drive_to_confirmed_breakout(tracker: CryptoRadarStateTracker) -> None:
    """Advancing transitions (including the initial move into BREAKOUT) are
    hysteresis-gated like any other - only FAILED_BREAKOUT/PUMP_RISK bypass
    it (see module docstring). So getting to CONFIRMED_BREAKOUT for a test
    means actually feeding `confirm_bars` matching bars, not asserting an
    immediate jump.
    """
    for _ in range(tracker.confirm_bars):
        tracker.update(price=101, breakout_level=100, rvol=2.6, clv=0.6, pump_risk=0.0)
    assert tracker.state == RadarState.BREAKOUT

    for _ in range(tracker.confirm_bars):
        tracker.update(price=102, breakout_level=100, rvol=2.0, clv=0.6, pump_risk=0.0)
    assert tracker.state == RadarState.CONFIRMED_BREAKOUT


def test_reaching_breakout_and_confirmed_breakout_is_hysteresis_gated_like_any_advance() -> None:
    _drive_to_confirmed_breakout(CryptoRadarStateTracker(confirm_bars=3))


def test_failed_breakout_bypasses_hysteresis() -> None:
    tracker = CryptoRadarStateTracker(confirm_bars=5)
    _drive_to_confirmed_breakout(tracker)

    # A single bar losing the level must fail it immediately - no waiting
    # for 5 confirmations while a real position sits unprotected.
    tracker.update(price=99, breakout_level=100, rvol=1.0, clv=-0.8, pump_risk=0.0)
    assert tracker.state == RadarState.FAILED_BREAKOUT


# --- pump-risk override --------------------------------------------------


def test_pump_risk_override_is_immediate_regardless_of_price_action() -> None:
    tracker = CryptoRadarStateTracker(confirm_bars=5, pump_risk_threshold=80.0)

    tracker.update(price=101, breakout_level=100, rvol=2.6, clv=0.6, pump_risk=95.0)

    assert tracker.state == RadarState.PUMP_RISK


def test_pump_risk_override_interrupts_a_pending_confirmation() -> None:
    tracker = CryptoRadarStateTracker(confirm_bars=3, pump_risk_threshold=80.0)
    tracker.update(price=98, breakout_level=100, rvol=1.5, clv=0.5, pump_risk=0.0)
    tracker.update(price=98, breakout_level=100, rvol=1.5, clv=0.5, pump_risk=0.0)

    tracker.update(price=98, breakout_level=100, rvol=1.5, clv=0.5, pump_risk=90.0)

    assert tracker.state == RadarState.PUMP_RISK


def test_leaving_pump_risk_requires_confirmation_not_a_single_bar() -> None:
    """Quick to flag risk, slower to clear it - the intended asymmetry."""
    tracker = CryptoRadarStateTracker(confirm_bars=2, pump_risk_threshold=80.0)
    tracker.update(price=101, breakout_level=100, rvol=2.0, clv=0.5, pump_risk=95.0)
    assert tracker.state == RadarState.PUMP_RISK

    tracker.update(price=95, breakout_level=100, rvol=0.5, clv=-0.5, pump_risk=0.0)
    assert tracker.state == RadarState.PUMP_RISK  # 1st bar after risk clears - not enough yet

    tracker.update(price=95, breakout_level=100, rvol=0.5, clv=-0.5, pump_risk=0.0)
    assert tracker.state == RadarState.STEALTH  # confirmed twice - now it can leave
