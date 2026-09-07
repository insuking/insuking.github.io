"""Risk + kill switch evaluation (P18).

Per docs/MASTER_SPEC.md: "risk per trade, max exposure, max positions,
daily risk, consecutive stop, market crash, pump risk, liquidity risk,
position mismatch, unknown order, Guardian unhealthy -> stop new trades
while existing protection remains."

That last clause is the load-bearing one: this module only ever answers
"should a *new* trade be allowed to start" - it has no opinion on, and no
ability to affect, what app/guardian/service.py does for positions already
open. Guardian's `process_position()` doesn't call anything here and never
will; keeping that boundary is what makes "existing protection remains"
true even when every check below is screaming.

`RiskState` (P1) already carries the current-value/limit pairs for
exposure, positions, and daily loss as one snapshot - this module checks
those directly rather than duplicating a second copy of the same limits.
Only the checks that snapshot doesn't cover (consecutive stops, market
regime, pump risk, liquidity, position/order integrity, Guardian health)
need a `RiskThresholds`/`RiskContext` of their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.domain import RiskState


@dataclass
class RiskThresholds:
    max_consecutive_stops: int = 3
    max_pump_risk_score: float = 80.0
    max_liquidity_slippage_pct: float = 1.0
    max_risk_per_trade_pct: float = 1.0


DEFAULT_THRESHOLDS = RiskThresholds()


@dataclass
class RiskContext:
    risk_state: RiskState
    guardian_healthy: bool = True
    market_crash: bool = False
    pump_risk_score: float | None = None
    liquidity_slippage_pct: float | None = None
    position_mismatch: bool = False
    unknown_order: bool = False


@dataclass
class KillSwitchReport:
    active: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_kill_switch(
    context: RiskContext, thresholds: RiskThresholds = DEFAULT_THRESHOLDS
) -> KillSwitchReport:
    reasons: list[str] = []
    rs = context.risk_state

    if rs.kill_switch_active:
        reasons.append(f"kill switch already active: {rs.kill_switch_reason or 'no reason recorded'}")
    if rs.exposure_limit > 0 and rs.exposure > rs.exposure_limit:
        reasons.append(f"exposure {rs.exposure:g} exceeds limit {rs.exposure_limit:g}")
    if rs.open_positions >= rs.max_positions:
        reasons.append(f"open positions {rs.open_positions} at/above max {rs.max_positions}")
    if rs.daily_loss_limit > 0 and rs.daily_loss > rs.daily_loss_limit:
        reasons.append(f"daily loss {rs.daily_loss:g} exceeds limit {rs.daily_loss_limit:g}")
    if rs.consecutive_stops >= thresholds.max_consecutive_stops:
        reasons.append(
            f"{rs.consecutive_stops} consecutive stops at/above max {thresholds.max_consecutive_stops}"
        )
    if context.market_crash:
        reasons.append("market crash / broad RISK_OFF regime detected")
    if context.pump_risk_score is not None and context.pump_risk_score >= thresholds.max_pump_risk_score:
        reasons.append(
            f"pump risk score {context.pump_risk_score:g} at/above max {thresholds.max_pump_risk_score:g}"
        )
    if (
        context.liquidity_slippage_pct is not None
        and context.liquidity_slippage_pct > thresholds.max_liquidity_slippage_pct
    ):
        reasons.append(
            f"estimated slippage {context.liquidity_slippage_pct:g}% exceeds max "
            f"{thresholds.max_liquidity_slippage_pct:g}%"
        )
    if context.position_mismatch:
        reasons.append("position mismatch between local records and broker")
    if context.unknown_order:
        reasons.append("an order is in UNKNOWN status and unresolved")
    if not context.guardian_healthy:
        reasons.append("Position Guardian is unhealthy")

    return KillSwitchReport(active=bool(reasons), reasons=reasons)


def exceeds_risk_per_trade(
    proposed_risk_amount: float, buying_power: float, thresholds: RiskThresholds = DEFAULT_THRESHOLDS
) -> bool:
    """Whether a single proposed trade's risk (the entry-to-stop dollar
    amount - see app/recommendation/engine.py's `position_size`) exceeds the
    per-trade cap. A non-positive `buying_power` is treated as "exceeds" -
    no verified buying power means no verified room to risk anything.
    """
    if buying_power <= 0:
        return True
    return (proposed_risk_amount / buying_power) * 100 > thresholds.max_risk_per_trade_pct
