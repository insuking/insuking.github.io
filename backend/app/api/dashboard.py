"""Dashboard read API (P21).

Backs the mobile home screen's five-second question (docs/MASTER_SPEC.md,
UX PRINCIPLES: "is the market safe right now? is there a recommendation?
does something need approval? are open positions safe? how much of today's
risk budget is left?") plus the 시장/성과/시스템 tabs - one aggregate
`/summary` call for the home screen (so it doesn't need six round trips to
answer a five-second question), and two focused endpoints for the tabs that
want more detail than the summary carries.

Every field here is computed from real rows in this deployment's own
database - nothing is sample/placeholder data. In a fresh or lightly-used
database that legitimately means empty lists and null regimes; the honest
answer to "what does the market look like" is "no data yet", not a
fabricated number (see app/paper_trading/cost_model.py's module docstring
for the same principle applied to cost rates).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.approval.service import TERMINAL_STATES
from app.core.config import get_settings
from app.db.models import Approval as ApprovalRow
from app.db.models import Candle as CandleRow
from app.db.models import (
    DailyDecisionRow,
    Incident,
    OverheatScoreRow,
    PaperFill,
    PaperOrder,
    RiskStateRow,
)
from app.db.models import Fill as FillRow
from app.db.models import Order as OrderRow
from app.db.models import Position as PositionRow
from app.db.models import Recommendation as RecommendationRow
from app.db.session import session_scope
from app.models.domain import (
    AssetType,
    Candle,
    HealthState,
    Position,
    PositionState,
    Recommendation,
    RiskState,
    SystemHealth,
)
from app.radar.regime import MarketRegime, classify_market_regime
from app.stock_radar.decision_persistence import get_latest_daily_decision
from app.supervisor import health_monitor, incident_manager

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_REGIME_MA_WINDOW = 20
_TOP_OPPORTUNITIES_LIMIT = 5
_UPBIT_BTC_SYMBOL = "KRW-BTC"


def _to_recommendation(row: RecommendationRow) -> Recommendation:
    return Recommendation(
        id=row.id,
        symbol=row.symbol,
        name=row.name,
        asset_type=AssetType(row.asset_type),
        score=row.score,
        state=row.state,
        entry_low=row.entry_low,
        entry_high=row.entry_high,
        stop_price=row.stop_price,
        t1_price=row.t1_price,
        t1_percent=row.t1_percent,
        t2_price=row.t2_price,
        t2_percent=row.t2_percent,
        runner_percent=row.runner_percent,
        expected_max_loss=row.expected_max_loss,
        risk_reward=row.risk_reward,
        reasons=json.loads(row.reasons),
        risks=json.loads(row.risks),
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


def _to_position(row: PositionRow) -> Position:
    return Position(
        id=row.id,
        symbol=row.symbol,
        asset_type=AssetType(row.asset_type),
        quantity=row.quantity,
        avg_entry_price=row.avg_entry_price,
        stop_price=row.stop_price,
        state=PositionState(row.state),
        guardian_active=row.guardian_active,
        opened_at=row.opened_at,
        updated_at=row.updated_at,
    )


def _to_risk_state(row: RiskStateRow) -> RiskState:
    return RiskState(
        as_of=row.as_of,
        daily_loss=row.daily_loss,
        daily_loss_limit=row.daily_loss_limit,
        exposure=row.exposure,
        exposure_limit=row.exposure_limit,
        open_positions=row.open_positions,
        max_positions=row.max_positions,
        consecutive_stops=row.consecutive_stops,
        kill_switch_active=row.kill_switch_active,
        kill_switch_reason=row.kill_switch_reason,
    )


def _to_system_health(sh: health_monitor.ServiceHealth) -> SystemHealth:
    return SystemHealth(service=sh.service, state=sh.state, detected_at=datetime.now(UTC), message=sh.detail)


@dataclass
class RegimeReading:
    regime: MarketRegime
    updated_at: datetime
    """The newest candle's `open_time` this reading was classified from -
    P37 (`app.radar.candle_persistence`) now actually keeps this fresh via
    the scheduler, so the 시장 tab can show "얼마나 최근 데이터인지" instead
    of a bare label with no way to judge whether it's stale."""


async def _latest_regime(
    session: AsyncSession, symbol: str, ma_window: int = _REGIME_MA_WINDOW
) -> RegimeReading | None:
    """`None` when there isn't enough real candle history yet for this
    symbol to classify - never a guessed regime from partial data."""
    result = await session.execute(
        select(CandleRow)
        .where(CandleRow.symbol == symbol)
        .order_by(CandleRow.open_time.desc())
        .limit(ma_window + 1)
    )
    rows = list(result.scalars().all())
    if len(rows) < ma_window + 1:
        return None
    rows.reverse()
    candles = [
        Candle(
            symbol=r.symbol,
            interval=r.interval,
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=r.volume,
            open_time=r.open_time,
            close_time=r.close_time,
        )
        for r in rows
    ]
    return RegimeReading(regime=classify_market_regime(candles, ma_window=ma_window), updated_at=rows[-1].open_time)


class DashboardSummary(BaseModel):
    market_regime: str | None
    market_regime_updated_at: datetime | None
    btc_regime: str | None
    btc_regime_updated_at: datetime | None
    overall_health: HealthState
    service_health: list[SystemHealth]
    open_incidents: int
    pending_approvals: int
    top_opportunities: list[Recommendation]
    positions: list[Position]
    risk_used: RiskState | None
    stock_decision_state: str | None
    stock_decision_reason: str | None
    stock_decision_top_symbol: str | None
    stock_decision_top_symbol_name: str | None
    stock_decision_observed_at: datetime | None


@router.get("/summary", response_model=DashboardSummary)
async def get_summary() -> DashboardSummary:
    settings = get_settings()
    async with session_scope() as session:
        db_health = await health_monitor.check_database_health()
        redis_health = await health_monitor.check_redis_health()
        guardian_health = await health_monitor.check_guardian_health(session)
        service_healths = [db_health, redis_health, guardian_health]
        overall = health_monitor.overall_state(service_healths)

        open_incidents = len(await incident_manager.open_unresolved_incidents(session))

        now = datetime.now(UTC)
        pending_result = await session.execute(
            select(func.count())
            .select_from(ApprovalRow)
            .where(ApprovalRow.state.not_in(TERMINAL_STATES), ApprovalRow.expires_at > now)
        )
        pending_approvals = pending_result.scalar_one()

        rec_result = await session.execute(
            select(RecommendationRow)
            .where(RecommendationRow.expires_at > now)
            .order_by(RecommendationRow.score.desc())
            .limit(_TOP_OPPORTUNITIES_LIMIT)
        )
        top_opportunities = [_to_recommendation(r) for r in rec_result.scalars().all()]

        pos_result = await session.execute(
            select(PositionRow).where(PositionRow.quantity > 0).order_by(PositionRow.opened_at.desc())
        )
        positions = [_to_position(p) for p in pos_result.scalars().all()]

        risk_result = await session.execute(select(RiskStateRow).order_by(RiskStateRow.as_of.desc()).limit(1))
        latest_risk = risk_result.scalar_one_or_none()
        risk_used = _to_risk_state(latest_risk) if latest_risk is not None else None

        market_regime = (
            await _latest_regime(session, settings.market_index_symbol)
            if settings.market_index_symbol
            else None
        )
        btc_regime = await _latest_regime(session, _UPBIT_BTC_SYMBOL)

        stock_decision = await get_latest_daily_decision(session)

    return DashboardSummary(
        market_regime=market_regime.regime.value if market_regime is not None else None,
        market_regime_updated_at=market_regime.updated_at if market_regime is not None else None,
        btc_regime=btc_regime.regime.value if btc_regime is not None else None,
        btc_regime_updated_at=btc_regime.updated_at if btc_regime is not None else None,
        overall_health=overall,
        service_health=[_to_system_health(sh) for sh in service_healths],
        open_incidents=open_incidents,
        pending_approvals=pending_approvals,
        top_opportunities=top_opportunities,
        positions=positions,
        risk_used=risk_used,
        stock_decision_state=stock_decision.decision_state if stock_decision is not None else None,
        stock_decision_reason=stock_decision.reason if stock_decision is not None else None,
        stock_decision_top_symbol=stock_decision.top_symbol if stock_decision is not None else None,
        stock_decision_top_symbol_name=stock_decision.top_symbol_name if stock_decision is not None else None,
        stock_decision_observed_at=stock_decision.observed_at if stock_decision is not None else None,
    )


class IncidentOut(BaseModel):
    id: str
    service: str
    severity: str
    failure_type: str
    detected_at: datetime
    safe_action: str | None
    recovery_attempts: int
    recovered_at: datetime | None
    verification_result: str | None
    human_action_required: bool


_INCIDENTS_LIMIT = 20


@router.get("/incidents", response_model=list[IncidentOut])
async def get_incidents() -> list[IncidentOut]:
    async with session_scope() as session:
        result = await session.execute(
            select(Incident).order_by(Incident.detected_at.desc()).limit(_INCIDENTS_LIMIT)
        )
        rows = list(result.scalars().all())

    return [
        IncidentOut(
            id=row.id,
            service=row.service,
            severity=row.severity,
            failure_type=row.failure_type,
            detected_at=row.detected_at,
            safe_action=row.safe_action,
            recovery_attempts=row.recovery_attempts,
            recovered_at=row.recovered_at,
            verification_result=row.verification_result,
            human_action_required=row.human_action_required,
        )
        for row in rows
    ]


@dataclass
class _PerformanceTotals:
    realized_pnl: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    trade_count: int = 0


class PerformanceSummary(BaseModel):
    realized_pnl: float
    win_count: int
    loss_count: int
    trade_count: int


class RiskAvoidanceSummary(BaseModel):
    """P36/P37: this project has no stock backtest harness yet (see
    docs/REGIME_ADAPTIVE_RADAR.md's "Known gaps"), so a real Bad-Trade/
    Chase-Avoidance-Rate KPI (needing tracked historical outcomes) isn't
    computable today - these are the honest, real counts this deployment
    actually has: how many candidates P35's TOO_LATE gate kept out of a
    recommendation, and how many days P36 correctly called "nothing worth
    buying" instead of forcing a pick, over the last 7 days."""

    too_late_excluded_count: int
    no_trade_day_count: int
    window_days: int


class DashboardPerformance(BaseModel):
    """`real` and `paper` are kept separate, never blended into one number -
    conflating simulated and real PnL on a trading dashboard is exactly the
    kind of "quietly wrong" mistake this project's safety rules exist to
    prevent."""

    real: PerformanceSummary
    paper: PerformanceSummary
    risk_avoidance: RiskAvoidanceSummary


def _accumulate_realized_pnl(fills_by_symbol: dict[str, list[tuple[str, float, float]]]) -> _PerformanceTotals:
    """Weighted-average-cost realized PnL per symbol, summed across the
    fill history it was given (same accounting model as
    app/partial_profit/accounting.py, minus the TradePlan-derived T1/T2
    state this summary doesn't need). A lifetime blend across every
    buy/sell cycle for a symbol - not a per-episode breakdown - which is
    the right level of detail for a glanceable dashboard total, not for
    trade-by-trade auditing."""
    totals = _PerformanceTotals()
    for fills in fills_by_symbol.values():
        buys = [(qty, price) for side, qty, price in fills if side == "BUY"]
        sells = [(qty, price) for side, qty, price in fills if side == "SELL"]
        entry_qty = sum(qty for qty, _ in buys)
        if entry_qty <= 0:
            continue
        avg_entry_price = sum(qty * price for qty, price in buys) / entry_qty
        for qty, price in sells:
            pnl = (price - avg_entry_price) * qty
            totals.realized_pnl += pnl
            totals.trade_count += 1
            if pnl > 0:
                totals.win_count += 1
            elif pnl < 0:
                totals.loss_count += 1
    return totals


_RISK_AVOIDANCE_WINDOW_DAYS = 7


@router.get("/performance", response_model=DashboardPerformance)
async def get_performance() -> DashboardPerformance:
    real_by_symbol: dict[str, list[tuple[str, float, float]]] = {}
    paper_by_symbol: dict[str, list[tuple[str, float, float]]] = {}

    async with session_scope() as session:
        window_start = datetime.now(UTC) - timedelta(days=_RISK_AVOIDANCE_WINDOW_DAYS)

        too_late_result = await session.execute(
            select(func.count())
            .select_from(OverheatScoreRow)
            .where(OverheatScoreRow.status == "TOO_LATE", OverheatScoreRow.observed_at >= window_start)
        )
        too_late_excluded_count = too_late_result.scalar_one()

        no_trade_result = await session.execute(
            select(func.count())
            .select_from(DailyDecisionRow)
            .where(DailyDecisionRow.decision_state == "NO_TRADE_DAY", DailyDecisionRow.observed_at >= window_start)
        )
        no_trade_day_count = no_trade_result.scalar_one()

        real_result = await session.execute(
            select(OrderRow.symbol, OrderRow.side, FillRow.quantity, FillRow.price, FillRow.filled_at)
            .join(FillRow, FillRow.order_id == OrderRow.id)
            .order_by(FillRow.filled_at.asc())
        )
        for symbol, side, quantity, price, _filled_at in real_result.all():
            real_by_symbol.setdefault(symbol, []).append((side, quantity, price))

        paper_result = await session.execute(
            select(PaperOrder.symbol, PaperOrder.side, PaperFill.quantity, PaperFill.price, PaperFill.filled_at)
            .join(PaperFill, PaperFill.order_id == PaperOrder.id)
            .order_by(PaperFill.filled_at.asc())
        )
        for symbol, side, quantity, price, _filled_at in paper_result.all():
            paper_by_symbol.setdefault(symbol, []).append((side, quantity, price))

    real_totals = _accumulate_realized_pnl(real_by_symbol)
    paper_totals = _accumulate_realized_pnl(paper_by_symbol)

    return DashboardPerformance(
        real=PerformanceSummary(
            realized_pnl=real_totals.realized_pnl,
            win_count=real_totals.win_count,
            loss_count=real_totals.loss_count,
            trade_count=real_totals.trade_count,
        ),
        paper=PerformanceSummary(
            realized_pnl=paper_totals.realized_pnl,
            win_count=paper_totals.win_count,
            loss_count=paper_totals.loss_count,
            trade_count=paper_totals.trade_count,
        ),
        risk_avoidance=RiskAvoidanceSummary(
            too_late_excluded_count=too_late_excluded_count,
            no_trade_day_count=no_trade_day_count,
            window_days=_RISK_AVOIDANCE_WINDOW_DAYS,
        ),
    )
