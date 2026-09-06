from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import AssetType
from app.radar.regime import MarketRegime
from app.radar.state import RadarState
from app.recommendation.engine import (
    RecommendationInputs,
    build_recommendation,
    position_size,
    score_recommendation,
)

pytestmark = pytest.mark.P6

NOW = datetime(2026, 1, 5, 9, 30, tzinfo=UTC)


def _inputs(**overrides: object) -> RecommendationInputs:
    defaults: dict[str, object] = {
        "symbol": "005930",
        "asset_type": AssetType.STOCK,
        "price": 101.0,
        "breakout_level": 100.0,
        "structural_stop": 97.0,
        "rvol": 2.5,
        "clv": 0.6,
        "relative_strength_value": 0.03,
        "regime": MarketRegime.RISK_ON,
        "radar_state": RadarState.CONFIRMED_BREAKOUT,
        "account_buying_power": 10_000_000.0,
        "now": NOW,
    }
    defaults.update(overrides)
    return RecommendationInputs(**defaults)  # type: ignore[arg-type]


# --- position sizing ---------------------------------------------------


def test_position_size_matches_risk_amount() -> None:
    qty = position_size(risk_amount=100_000, entry_price=101, stop_price=97)
    assert qty == pytest.approx(100_000 / 4)


def test_position_size_zero_when_stop_not_below_entry() -> None:
    assert position_size(risk_amount=100_000, entry_price=100, stop_price=100) == 0.0
    assert position_size(risk_amount=100_000, entry_price=100, stop_price=105) == 0.0


# --- scoring -------------------------------------------------------------


def test_score_increases_with_breakout_stage() -> None:
    def score(state: RadarState) -> float:
        return score_recommendation(
            state, rvol=1.0, relative_strength_value=0.0, regime=MarketRegime.NEUTRAL
        )

    assert score(RadarState.PRE_BREAKOUT) < score(RadarState.BREAKOUT) < score(
        RadarState.CONFIRMED_BREAKOUT
    )


def test_score_is_clamped_to_0_100() -> None:
    high = score_recommendation(
        RadarState.CONFIRMED_BREAKOUT, rvol=100, relative_strength_value=1.0, regime=MarketRegime.RISK_ON
    )
    assert high == 100.0

    low = score_recommendation(
        RadarState.PRE_BREAKOUT, rvol=0.0, relative_strength_value=-1.0, regime=MarketRegime.NEUTRAL
    )
    assert low >= 0.0


def test_score_rewards_relative_strength_and_regime() -> None:
    base = score_recommendation(
        RadarState.BREAKOUT, rvol=1.0, relative_strength_value=0.0, regime=MarketRegime.NEUTRAL
    )
    better_rs = score_recommendation(
        RadarState.BREAKOUT, rvol=1.0, relative_strength_value=0.05, regime=MarketRegime.NEUTRAL
    )
    risk_on = score_recommendation(
        RadarState.BREAKOUT, rvol=1.0, relative_strength_value=0.0, regime=MarketRegime.RISK_ON
    )
    assert better_rs > base
    assert risk_on > base


# --- gating ----------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        RadarState.STEALTH,
        RadarState.ACCUMULATION,
        RadarState.PULLBACK,
        RadarState.DISTRIBUTION,
        RadarState.RE_ENTRY,
        RadarState.FAILED_BREAKOUT,
        RadarState.PUMP_RISK,
        RadarState.AVOID,
    ],
)
def test_no_recommendation_outside_eligible_states(state: RadarState) -> None:
    assert build_recommendation(_inputs(radar_state=state)) is None


def test_no_recommendation_in_risk_off_market() -> None:
    assert build_recommendation(_inputs(regime=MarketRegime.RISK_OFF)) is None


def test_no_recommendation_when_stop_is_not_below_entry() -> None:
    assert build_recommendation(_inputs(structural_stop=101.0)) is None
    assert build_recommendation(_inputs(structural_stop=105.0)) is None


# --- happy path content ------------------------------------------------


def test_build_recommendation_computes_entry_stop_targets_and_sizing() -> None:
    rec = build_recommendation(_inputs())
    assert rec is not None

    r = 101.0 - 97.0  # entry - stop
    assert rec.entry_low == 101.0
    assert rec.entry_high == pytest.approx(101.0 * 1.005)
    assert rec.stop_price == 97.0
    assert rec.t1_price == pytest.approx(101.0 + r * 1.5)
    assert rec.t2_price == pytest.approx(101.0 + r * 3.0)
    assert (rec.t1_percent, rec.t2_percent, rec.runner_percent) == (30.0, 30.0, 40.0)
    assert rec.risk_reward == pytest.approx((rec.t2_price - 101.0) / r)

    expected_qty = (10_000_000.0 * 0.01) / r
    assert rec.expected_max_loss == pytest.approx(expected_qty * r)
    assert rec.expected_max_loss == pytest.approx(10_000_000.0 * 0.01)


def test_build_recommendation_sets_ttl_from_created_at() -> None:
    rec = build_recommendation(_inputs(ttl_seconds=120))
    assert rec is not None
    assert rec.created_at == NOW
    assert rec.expires_at == NOW + timedelta(seconds=120)


def test_build_recommendation_never_fabricates_positive_risk_reward_without_risk() -> None:
    rec = build_recommendation(_inputs())
    assert rec is not None
    assert rec.risk_reward > 0


def test_reasons_and_risks_are_populated() -> None:
    rec = build_recommendation(_inputs())
    assert rec is not None
    assert len(rec.reasons) > 0
    assert len(rec.risks) > 0


def test_low_volume_setup_is_flagged_as_a_risk() -> None:
    rec = build_recommendation(_inputs(rvol=1.1, relative_strength_value=0.02))
    assert rec is not None
    assert any("volume" in r.lower() for r in rec.risks)


def test_neutral_regime_recommendation_notes_the_regime_as_a_risk() -> None:
    rec = build_recommendation(_inputs(regime=MarketRegime.NEUTRAL))
    assert rec is not None
    assert any("neutral" in r.lower() for r in rec.risks)
