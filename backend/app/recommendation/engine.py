"""Stock recommendation engine (P6).

Turns P4's radar signals into a P1 `Recommendation` - entry zone, structural
stop, T1/T2, runner %, position size, expected risk, R:R, reasons, risks,
and a TTL. This produces a *recommendation*, never an order: docs/MASTER_SPEC.md
section B is explicit that ranking, recommendation, and approval are three
separate steps, and this phase implements none of the order-placement
machinery (that's P15) or the approval flow (P13/P14).

Gating is deliberately conservative: no recommendation at all (`None`) when
the setup or the market backdrop doesn't support one, rather than emitting a
low-confidence recommendation and relying on the score alone to signal that.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models.domain import AssetType, Recommendation
from app.radar.regime import MarketRegime
from app.radar.state import RadarState

ELIGIBLE_STATES = (RadarState.PRE_BREAKOUT, RadarState.BREAKOUT, RadarState.CONFIRMED_BREAKOUT)

_BASE_SCORE_BY_STATE = {
    RadarState.PRE_BREAKOUT: 55.0,
    RadarState.BREAKOUT: 70.0,
    RadarState.CONFIRMED_BREAKOUT: 85.0,
}

DEFAULT_T1_R_MULTIPLE = 1.5
DEFAULT_T2_R_MULTIPLE = 3.0
DEFAULT_T1_PERCENT = 30.0
DEFAULT_T2_PERCENT = 30.0
DEFAULT_RUNNER_PERCENT = 40.0
DEFAULT_TTL_SECONDS = 300
DEFAULT_RISK_PER_TRADE = 0.01  # 1% of buying power risked per trade


@dataclass
class RecommendationInputs:
    symbol: str
    asset_type: AssetType
    price: float
    breakout_level: float
    structural_stop: float
    rvol: float
    clv: float
    relative_strength_value: float
    regime: MarketRegime
    radar_state: RadarState
    account_buying_power: float
    risk_per_trade: float = DEFAULT_RISK_PER_TRADE
    t1_r_multiple: float = DEFAULT_T1_R_MULTIPLE
    t2_r_multiple: float = DEFAULT_T2_R_MULTIPLE
    ttl_seconds: int = DEFAULT_TTL_SECONDS
    now: datetime | None = None


def position_size(risk_amount: float, entry_price: float, stop_price: float) -> float:
    """Quantity such that (entry - stop) * quantity == risk_amount."""
    per_unit_risk = entry_price - stop_price
    if per_unit_risk <= 0:
        return 0.0
    return risk_amount / per_unit_risk


def score_recommendation(
    radar_state: RadarState, rvol: float, relative_strength_value: float, regime: MarketRegime
) -> float:
    """0-100 composite score. Weights are fixed and documented, not a black box:

    - base score by breakout stage (55/70/85)
    - up to +15 for RVOL above 1x average, capped
    - +/-10 for relative strength vs. benchmark (as a fraction, e.g. 0.06 = 6%)
    - +5 in a RISK_ON market, -5 in NEUTRAL (RISK_OFF never reaches this
      function - see build_recommendation)
    """
    score = _BASE_SCORE_BY_STATE.get(radar_state, 0.0)
    score += min(max(rvol - 1.0, 0.0) * 5, 15.0)
    score += max(min(relative_strength_value * 100, 10.0), -10.0)
    if regime == MarketRegime.RISK_ON:
        score += 5.0
    elif regime == MarketRegime.NEUTRAL:
        score -= 5.0
    return max(0.0, min(100.0, score))


def _build_reasons(inputs: RecommendationInputs) -> list[str]:
    reasons = []
    if inputs.radar_state == RadarState.CONFIRMED_BREAKOUT:
        reasons.append("Confirmed breakout above the opening range high")
    elif inputs.radar_state == RadarState.BREAKOUT:
        reasons.append("Fresh breakout above the opening range high")
    elif inputs.radar_state == RadarState.PRE_BREAKOUT:
        reasons.append("Approaching the opening range high on rising volume")
    if inputs.rvol >= 2.0:
        reasons.append(f"RVOL {inputs.rvol:.1f}x average volume")
    if inputs.relative_strength_value > 0:
        reasons.append(f"Outperforming the benchmark by {inputs.relative_strength_value * 100:.1f}%")
    if inputs.clv >= 0.3:
        reasons.append("Closing strong near the session high")
    if inputs.regime == MarketRegime.RISK_ON:
        reasons.append("Broad market regime is RISK_ON")
    return reasons


def _build_risks(inputs: RecommendationInputs) -> list[str]:
    risks = []
    if inputs.regime == MarketRegime.NEUTRAL:
        risks.append("Market regime is NEUTRAL - mixed trend signal")
    if inputs.rvol < 1.5:
        risks.append("Volume confirmation is modest")
    if inputs.relative_strength_value < 0:
        risks.append("Underperforming the benchmark")
    if not risks:
        risks.append("Standard breakout risk: the level can fail after triggering (failed breakout)")
    return risks


def build_recommendation(inputs: RecommendationInputs) -> Recommendation | None:
    """Returns None when the setup or market backdrop doesn't warrant a recommendation."""
    if inputs.radar_state not in ELIGIBLE_STATES:
        return None
    if inputs.regime == MarketRegime.RISK_OFF:
        return None

    entry_low = inputs.price
    entry_high = inputs.price * 1.005
    stop_price = inputs.structural_stop
    r = entry_low - stop_price
    if r <= 0:
        # Structural stop is at or above the entry - not a valid risk setup.
        return None

    t1_price = entry_low + r * inputs.t1_r_multiple
    t2_price = entry_low + r * inputs.t2_r_multiple

    risk_amount = inputs.account_buying_power * inputs.risk_per_trade
    quantity = position_size(risk_amount, entry_low, stop_price)
    expected_max_loss = quantity * r
    risk_reward = (t2_price - entry_low) / r

    score = score_recommendation(
        inputs.radar_state, inputs.rvol, inputs.relative_strength_value, inputs.regime
    )

    now = inputs.now or datetime.now(UTC)

    return Recommendation(
        id=str(uuid.uuid4()),
        symbol=inputs.symbol,
        asset_type=inputs.asset_type,
        score=score,
        state=inputs.radar_state.value,
        entry_low=entry_low,
        entry_high=entry_high,
        stop_price=stop_price,
        t1_price=t1_price,
        t1_percent=DEFAULT_T1_PERCENT,
        t2_price=t2_price,
        t2_percent=DEFAULT_T2_PERCENT,
        runner_percent=DEFAULT_RUNNER_PERCENT,
        expected_max_loss=expected_max_loss,
        risk_reward=risk_reward,
        reasons=_build_reasons(inputs),
        risks=_build_risks(inputs),
        created_at=now,
        expires_at=now + timedelta(seconds=inputs.ttl_seconds),
    )
