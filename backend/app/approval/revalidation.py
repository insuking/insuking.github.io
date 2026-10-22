"""Pre-order revalidation (P14).

After a user approves (P13), don't trust that the market still looks the
way it did at recommendation time by the time an order would actually be
placed - re-check price, the technical signal, liquidity, and the broader
regime one more time. See docs/MASTER_SPEC.md section F for the exact list
this maps onto: "current price, entry deviation, signal score/state, VWAP,
RVOL, turnover, spread, slippage, liquidity, BTC/stock regime, market data
health, execution API health, portfolio exposure, daily loss, position
duplication."

Pure function over an explicit `RevalidationInput` bundle rather than
reaching into live systems itself: portfolio exposure/daily-loss (P1's
`RiskState`) and broker/market-data health (P19's watchdog) are owned by
phases that don't exist yet, so this takes them as typed parameters instead
of pretending to fetch them live - the same "assemble already-fetched data,
compute a pure verdict" shape as P4/P8/P10/P11's feature modules.

`ensemble_score` (P10) and the `RiskState` scale are unrelated 0-100/ratio
systems, on purpose - this doesn't try to average them into
`Recommendation.score`, it treats "has the technical picture turned
bearish since approval" as its own independent check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.db.models import Recommendation as RecommendationRow
from app.models.domain import Candle, OrderBook, OrderSide, RiskState
from app.radar.crypto_features import estimate_slippage, spread
from app.radar.features import relative_volume
from app.radar.regime import MarketRegime, classify_market_regime
from app.technical.ensemble import MIN_CANDLES, ensemble_score


class RevalidationVerdict(str, Enum):
    VALID = "VALID"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


@dataclass
class RevalidationThresholds:
    max_entry_drift_pct: float = 0.5
    min_rvol: float = 1.0
    max_spread_pct: float = 0.5
    max_slippage_pct: float = 1.0
    min_ensemble_score: float = 0.0
    max_exposure_ratio: float = 1.0
    max_daily_loss_ratio: float = 1.0


DEFAULT_THRESHOLDS = RevalidationThresholds()


@dataclass
class RevalidationInput:
    now: datetime
    approval_expires_at: datetime
    recommendation: RecommendationRow
    current_price: float
    recent_candles: list[Candle] = field(default_factory=list)
    average_volume: float = 0.0
    benchmark_candles: list[Candle] = field(default_factory=list)
    orderbook: OrderBook | None = None
    risk_state: RiskState | None = None
    market_data_healthy: bool = True
    broker_healthy: bool = True
    position_already_open: bool = False


@dataclass
class RevalidationReport:
    verdict: RevalidationVerdict
    reasons: list[str] = field(default_factory=list)


def revalidate(
    data: RevalidationInput, thresholds: RevalidationThresholds = DEFAULT_THRESHOLDS
) -> RevalidationReport:
    if data.now >= data.approval_expires_at:
        return RevalidationReport(verdict=RevalidationVerdict.EXPIRED, reasons=["approval TTL elapsed"])

    reasons: list[str] = []
    rec = data.recommendation

    if data.current_price <= rec.stop_price:
        reasons.append(f"price {data.current_price:g} has already fallen to/through the stop {rec.stop_price:g}")
    else:
        drift_pct = max(0.0, (data.current_price - rec.entry_high) / rec.entry_high * 100)
        if drift_pct > thresholds.max_entry_drift_pct:
            reasons.append(
                f"entry has drifted {drift_pct:.2f}% past entry_high (max {thresholds.max_entry_drift_pct}%)"
            )

    if not data.market_data_healthy:
        reasons.append("market data feed is unhealthy")
    if not data.broker_healthy:
        reasons.append("execution broker is unhealthy")
    if data.position_already_open:
        reasons.append("a position in this symbol is already open")

    if data.risk_state is not None:
        rs = data.risk_state
        if rs.kill_switch_active:
            reasons.append(f"risk kill switch is active ({rs.kill_switch_reason or 'no reason given'})")
        if rs.exposure_limit > 0 and rs.exposure / rs.exposure_limit > thresholds.max_exposure_ratio:
            reasons.append("portfolio exposure limit would be exceeded")
        if rs.daily_loss_limit > 0 and rs.daily_loss / rs.daily_loss_limit > thresholds.max_daily_loss_ratio:
            reasons.append("daily loss limit would be exceeded")

    if data.average_volume > 0 and data.recent_candles:
        current_volume = data.recent_candles[-1].volume
        rvol = relative_volume(current_volume, data.average_volume)
        if rvol < thresholds.min_rvol:
            reasons.append(f"RVOL dropped to {rvol:.2f}x (min {thresholds.min_rvol}x)")

    if data.orderbook is not None:
        spread_pct = spread(data.orderbook) * 100
        if spread_pct > thresholds.max_spread_pct:
            reasons.append(f"spread widened to {spread_pct:.2f}% (max {thresholds.max_spread_pct}%)")

        risk_per_unit = rec.entry_low - rec.stop_price
        quantity = rec.expected_max_loss / risk_per_unit if risk_per_unit > 0 else 0.0
        if quantity > 0:
            slippage_pct = estimate_slippage(data.orderbook, OrderSide.BUY, quantity) * 100
            if slippage_pct > thresholds.max_slippage_pct:
                reasons.append(
                    f"estimated slippage {slippage_pct:.2f}% exceeds max {thresholds.max_slippage_pct}%"
                )

    if data.benchmark_candles:
        regime = classify_market_regime(data.benchmark_candles)
        if regime == MarketRegime.RISK_OFF:
            reasons.append("market regime has turned RISK_OFF since approval")

    if len(data.recent_candles) >= MIN_CANDLES:
        current_score = ensemble_score(data.recent_candles)
        if current_score is not None and current_score.score < thresholds.min_ensemble_score:
            reasons.append(
                f"technical ensemble score has turned bearish ({current_score.score:.1f})"
            )

    verdict = RevalidationVerdict.INVALIDATED if reasons else RevalidationVerdict.VALID
    return RevalidationReport(verdict=verdict, reasons=reasons)
