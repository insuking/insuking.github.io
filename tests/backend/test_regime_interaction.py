import pytest

from app.stock_radar.regime_interaction import (
    InteractionLabel,
    compute_interaction_score,
)

pytestmark = pytest.mark.P34


def test_strong_resilience_when_stock_up_one_percent_in_a_weak_market() -> None:
    result = compute_interaction_score(
        benchmark_return_pct=-2.0, stock_return_pct=1.5, foreign_net_today=0.0, institution_net_today=0.0
    )
    assert result.weak_market_resilience_score == pytest.approx(2.0)
    assert result.label == InteractionLabel.STRONG_RELATIVE_STRENGTH


def test_mild_resilience_when_stock_flat_in_a_weak_market() -> None:
    result = compute_interaction_score(
        benchmark_return_pct=-2.0, stock_return_pct=0.2, foreign_net_today=0.0, institution_net_today=0.0
    )
    assert result.weak_market_resilience_score == pytest.approx(1.0)
    assert result.label == InteractionLabel.WEAK_MARKET_RESILIENT


def test_tiers_never_stack_the_strong_tier_implies_the_mild_one_only_once() -> None:
    result = compute_interaction_score(
        benchmark_return_pct=-2.0, stock_return_pct=3.0, foreign_net_today=0.0, institution_net_today=0.0
    )
    # +1% tier alone, never +2 and +1 both applied.
    assert result.weak_market_resilience_score == pytest.approx(2.0)


def test_no_resilience_bonus_when_market_is_not_actually_weak() -> None:
    result = compute_interaction_score(
        benchmark_return_pct=-0.5, stock_return_pct=5.0, foreign_net_today=0.0, institution_net_today=0.0
    )
    assert result.weak_market_resilience_score == 0.0
    assert result.label == InteractionLabel.NEUTRAL


def test_flow_resilience_bonus_when_market_plunges_with_both_investor_classes_buying() -> None:
    result = compute_interaction_score(
        benchmark_return_pct=-2.0, stock_return_pct=-1.0, foreign_net_today=500.0, institution_net_today=300.0
    )
    assert result.flow_resilience_score == pytest.approx(2.0)
    assert result.label == InteractionLabel.STRONG_RELATIVE_STRENGTH


def test_flow_resilience_bonus_requires_both_classes_buying_not_just_a_positive_sum() -> None:
    # Foreign heavily selling, institution buying more - net sum positive,
    # but not "동반매수" (both classes actually buying).
    result = compute_interaction_score(
        benchmark_return_pct=-2.0, stock_return_pct=-1.0, foreign_net_today=-1000.0, institution_net_today=1500.0
    )
    assert result.flow_resilience_score == 0.0


def test_flow_not_persistent_penalty_when_yesterdays_buying_did_not_carry_through() -> None:
    result = compute_interaction_score(
        benchmark_return_pct=-0.5,
        stock_return_pct=-2.0,
        foreign_net_today=0.0,
        institution_net_today=0.0,
        foreign_net_prev_day=500.0,
        institution_net_prev_day=300.0,
    )
    assert result.flow_resilience_score == pytest.approx(-3.0)
    assert result.label == InteractionLabel.FLOW_NOT_PERSISTENT


def test_flow_not_persistent_penalty_not_applied_when_stock_still_beats_the_benchmark() -> None:
    result = compute_interaction_score(
        benchmark_return_pct=-2.0,
        stock_return_pct=-1.0,  # underperforms in absolute terms but still beats the -2.0% benchmark
        foreign_net_today=0.0,
        institution_net_today=0.0,
        foreign_net_prev_day=500.0,
        institution_net_prev_day=300.0,
    )
    assert result.flow_resilience_score == 0.0


def test_flow_not_persistent_penalty_skipped_without_prior_day_data() -> None:
    result = compute_interaction_score(
        benchmark_return_pct=-0.5, stock_return_pct=-3.0, foreign_net_today=0.0, institution_net_today=0.0
    )
    assert result.flow_resilience_score == 0.0
    assert result.label == InteractionLabel.NEUTRAL


def test_interaction_score_is_the_sum_of_both_components() -> None:
    result = compute_interaction_score(
        benchmark_return_pct=-2.0, stock_return_pct=1.5, foreign_net_today=500.0, institution_net_today=300.0
    )
    assert result.interaction_score == pytest.approx(
        result.weak_market_resilience_score + result.flow_resilience_score
    )
    assert result.interaction_score == pytest.approx(4.0)  # +2 resilience, +2 flow
