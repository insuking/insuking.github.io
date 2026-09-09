"""P27: entry confirmation (pure) - the "진입필터" gap/regime check between
a P23 PRE-BREAKOUT score and acting on it later.
"""

from __future__ import annotations

import pytest

from app.radar.regime import MarketRegime
from app.stock_radar.entry_confirmation import (
    EntryConfirmationThresholds,
    EntryVerdict,
    confirm_entry,
)
from app.stock_radar.scoring import PreBreakoutScore

pytestmark = pytest.mark.P27


def _score(reference_close: float = 100.0) -> PreBreakoutScore:
    return PreBreakoutScore(symbol="005930", total_score=40.0, max_available=65.0, reference_close=reference_close)


def test_unchanged_price_in_a_risk_on_market_is_confirmed() -> None:
    result = confirm_entry(_score(100.0), current_price=100.0, regime=MarketRegime.RISK_ON)

    assert result.verdict == EntryVerdict.CONFIRMED
    assert result.gap_pct == pytest.approx(0.0)
    assert result.reasons == []


def test_a_small_gap_up_within_threshold_is_confirmed() -> None:
    result = confirm_entry(_score(100.0), current_price=102.0, regime=MarketRegime.RISK_ON)

    assert result.verdict == EntryVerdict.CONFIRMED
    assert result.gap_pct == pytest.approx(2.0)


def test_a_large_gap_up_is_rejected_as_chasing() -> None:
    result = confirm_entry(_score(100.0), current_price=105.0, regime=MarketRegime.RISK_ON)

    assert result.verdict == EntryVerdict.REJECTED
    assert result.gap_pct == pytest.approx(5.0)
    assert any("갭업" in r for r in result.reasons)


def test_a_large_gap_down_is_rejected_as_thesis_broken() -> None:
    result = confirm_entry(_score(100.0), current_price=94.0, regime=MarketRegime.RISK_ON)

    assert result.verdict == EntryVerdict.REJECTED
    assert result.gap_pct == pytest.approx(-6.0)
    assert any("갭다운" in r for r in result.reasons)


def test_risk_off_regime_is_rejected_even_with_no_gap() -> None:
    result = confirm_entry(_score(100.0), current_price=100.0, regime=MarketRegime.RISK_OFF)

    assert result.verdict == EntryVerdict.REJECTED
    assert any("RISK_OFF" in r for r in result.reasons)


def test_a_zero_reference_close_is_rejected_rather_than_dividing_by_zero() -> None:
    result = confirm_entry(_score(0.0), current_price=100.0, regime=MarketRegime.RISK_ON)

    assert result.verdict == EntryVerdict.REJECTED
    assert result.gap_pct == pytest.approx(0.0)


def test_custom_thresholds_change_the_verdict() -> None:
    tight = EntryConfirmationThresholds(max_gap_up_pct=1.0, max_gap_down_pct=1.0)

    default_result = confirm_entry(_score(100.0), current_price=102.0, regime=MarketRegime.RISK_ON)
    tight_result = confirm_entry(_score(100.0), current_price=102.0, regime=MarketRegime.RISK_ON, thresholds=tight)

    assert default_result.verdict == EntryVerdict.CONFIRMED
    assert tight_result.verdict == EntryVerdict.REJECTED
