import pytest

from app.radar.regime import MarketRegime
from app.stock_radar.decision import (
    DecisionState,
    decide_daily_state,
    decide_entry_state,
    dynamic_minimum_score,
)
from app.stock_radar.overheat import HeatStatus

pytestmark = pytest.mark.P36


@pytest.mark.parametrize(
    ("regime", "expected"),
    [
        (MarketRegime.RISK_ON, 80.0),
        (MarketRegime.NEUTRAL, 82.0),
        (MarketRegime.RISK_OFF, 85.0),
    ],
)
def test_dynamic_minimum_score_rises_as_the_regime_worsens(regime: MarketRegime, expected: float) -> None:
    assert dynamic_minimum_score(regime) == expected


def test_strong_buy_when_score_clears_the_bar_all_filters_pass_and_heat_is_calm() -> None:
    decision = decide_entry_state(
        normalized_score=89.0,
        regime=MarketRegime.RISK_ON,
        heat_status=HeatStatus.NORMAL,
        entry_filters_passed=5,
        entry_filters_total=5,
    )
    assert decision.state == DecisionState.STRONG_BUY


def test_too_late_forces_no_buy_even_with_a_high_score_and_all_filters_passed() -> None:
    decision = decide_entry_state(
        normalized_score=91.0,
        regime=MarketRegime.RISK_ON,
        heat_status=HeatStatus.TOO_LATE,
        entry_filters_passed=5,
        entry_filters_total=5,
    )
    assert decision.state == DecisionState.NO_BUY
    assert "TOO_LATE" in decision.reason


def test_no_buy_when_score_is_below_the_regime_minimum() -> None:
    decision = decide_entry_state(
        normalized_score=73.0,
        regime=MarketRegime.RISK_OFF,
        heat_status=HeatStatus.NORMAL,
        entry_filters_passed=3,
        entry_filters_total=5,
    )
    assert decision.state == DecisionState.NO_BUY


def test_buy_when_score_clears_the_bar_and_only_one_filter_is_missing() -> None:
    decision = decide_entry_state(
        normalized_score=86.0,
        regime=MarketRegime.NEUTRAL,
        heat_status=HeatStatus.WARM,
        entry_filters_passed=4,
        entry_filters_total=5,
    )
    assert decision.state == DecisionState.BUY


def test_watch_when_score_clears_the_bar_but_too_few_filters_pass() -> None:
    decision = decide_entry_state(
        normalized_score=86.0,
        regime=MarketRegime.NEUTRAL,
        heat_status=HeatStatus.NORMAL,
        entry_filters_passed=2,
        entry_filters_total=5,
    )
    assert decision.state == DecisionState.WATCH


def test_very_hot_downgrades_an_otherwise_full_pass_from_strong_buy_to_watch() -> None:
    decision = decide_entry_state(
        normalized_score=89.0,
        regime=MarketRegime.RISK_ON,
        heat_status=HeatStatus.VERY_HOT,
        entry_filters_passed=5,
        entry_filters_total=5,
    )
    assert decision.state == DecisionState.WATCH


def test_daily_state_is_no_trade_day_when_no_candidate_scanned_today() -> None:
    assert decide_daily_state(None) == DecisionState.NO_TRADE_DAY


def test_daily_state_is_no_trade_day_when_the_best_candidate_is_only_a_watch() -> None:
    best = decide_entry_state(
        normalized_score=73.0,
        regime=MarketRegime.RISK_OFF,
        heat_status=HeatStatus.NORMAL,
        entry_filters_passed=3,
        entry_filters_total=5,
    )
    assert decide_daily_state(best) == DecisionState.NO_TRADE_DAY


def test_daily_state_mirrors_the_best_candidates_buy_state() -> None:
    best = decide_entry_state(
        normalized_score=89.0,
        regime=MarketRegime.RISK_ON,
        heat_status=HeatStatus.NORMAL,
        entry_filters_passed=5,
        entry_filters_total=5,
    )
    assert decide_daily_state(best) == DecisionState.STRONG_BUY
