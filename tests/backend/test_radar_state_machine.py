"""Radar state machine tests (P4), including the Kia failed-breakout regression.

Note on the Kia fixture: this repository has no live KIS market data yet
(P3's real connection is BLOCKED without credentials - see
docs/KIS_SETUP.md), so the fixture below is a synthetic bar sequence
constructed to exhibit the textbook "failed breakout" pattern the master
spec calls out for Kia (000270): a clean break above the opening range on
rising volume, apparent confirmation, then a reversal that closes back
below the breakout level. It is NOT real historical Kia prints - it is a
regression fixture for the pattern archetype. Replace it with a real
labeled Kia session once KIS credentials and historical data access exist.
"""

import pytest

from app.radar.state import DEFAULT_THRESHOLDS, RadarState, next_state

pytestmark = pytest.mark.P4


def test_stealth_when_signals_are_flat() -> None:
    state = next_state(RadarState.STEALTH, price=95, breakout_level=100, rvol=0.8, clv=0.0)
    assert state == RadarState.STEALTH


def test_accumulation_when_volume_and_buying_pressure_build() -> None:
    state = next_state(RadarState.STEALTH, price=98, breakout_level=100, rvol=1.5, clv=0.4)
    assert state == RadarState.ACCUMULATION


def test_pre_breakout_when_price_nears_level_on_high_volume() -> None:
    state = next_state(RadarState.ACCUMULATION, price=99.6, breakout_level=100, rvol=2.5, clv=0.4)
    assert state == RadarState.PRE_BREAKOUT


def test_breakout_when_price_closes_above_level() -> None:
    state = next_state(RadarState.PRE_BREAKOUT, price=101, breakout_level=100, rvol=2.5, clv=0.5)
    assert state == RadarState.BREAKOUT


def test_confirmed_breakout_on_strong_follow_through() -> None:
    state = next_state(RadarState.BREAKOUT, price=103, breakout_level=100, rvol=2.0, clv=0.6)
    assert state == RadarState.CONFIRMED_BREAKOUT


def test_pullback_on_mild_weakness_while_still_above_level() -> None:
    state = next_state(RadarState.CONFIRMED_BREAKOUT, price=101, breakout_level=100, rvol=1.0, clv=0.0)
    assert state == RadarState.PULLBACK


def test_distribution_on_weak_close_while_still_above_level() -> None:
    state = next_state(RadarState.CONFIRMED_BREAKOUT, price=101, breakout_level=100, rvol=1.5, clv=-0.5)
    assert state == RadarState.DISTRIBUTION


def test_re_entry_from_distribution_on_renewed_buying() -> None:
    state = next_state(RadarState.DISTRIBUTION, price=102, breakout_level=100, rvol=1.5, clv=0.5)
    assert state == RadarState.RE_ENTRY


def test_failed_breakout_when_confirmed_breakout_loses_the_level() -> None:
    state = next_state(RadarState.CONFIRMED_BREAKOUT, price=99, breakout_level=100, rvol=1.0, clv=-0.8)
    assert state == RadarState.FAILED_BREAKOUT


def test_failed_breakout_stays_failed_until_level_is_reclaimed() -> None:
    state = next_state(RadarState.FAILED_BREAKOUT, price=98, breakout_level=100, rvol=0.9, clv=-0.2)
    assert state == RadarState.FAILED_BREAKOUT


def test_reclaiming_level_after_failed_breakout_starts_a_new_breakout() -> None:
    state = next_state(RadarState.FAILED_BREAKOUT, price=101, breakout_level=100, rvol=1.8, clv=0.5)
    assert state == RadarState.BREAKOUT


def test_kia_failed_breakout_regression() -> None:
    """005930-style single-day sequence for 000270 (기아): breaks the opening
    range high on strong volume, looks confirmed for two bars, then reverses
    and closes back below the breakout level - the state machine must call
    this FAILED_BREAKOUT, not keep it as CONFIRMED_BREAKOUT or soften it to
    PULLBACK (which is reserved for staying above the level).
    """
    breakout_level = 100.0
    # (price, rvol, clv) per bar, in session order. Each comment names the
    # state that bar's transition produces (starting from initial STEALTH).
    bars = [
        (98.5, 1.4, 0.4),  # -> ACCUMULATION
        (99.7, 2.2, 0.5),  # -> PRE_BREAKOUT
        (101.0, 2.6, 0.6),  # -> BREAKOUT
        (102.5, 2.1, 0.7),  # -> CONFIRMED_BREAKOUT
        (102.0, 1.3, 0.5),  # -> still CONFIRMED_BREAKOUT (healthy, above level, good clv)
        (99.0, 1.6, -0.6),  # -> reversal: closes back below breakout_level
    ]

    state = RadarState.STEALTH
    history = [state]
    for price, rvol, clv in bars:
        state = next_state(state, price, breakout_level, rvol, clv, DEFAULT_THRESHOLDS)
        history.append(state)

    assert history == [
        RadarState.STEALTH,
        RadarState.ACCUMULATION,
        RadarState.PRE_BREAKOUT,
        RadarState.BREAKOUT,
        RadarState.CONFIRMED_BREAKOUT,
        RadarState.CONFIRMED_BREAKOUT,
        RadarState.FAILED_BREAKOUT,
    ]
