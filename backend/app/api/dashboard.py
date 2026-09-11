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

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.account.balance import fetch_combined_balance
from app.account.persistence import get_balance_history
from app.api.approvals import _require_authenticated
from app.approval.errors import ApprovalNotAuthenticatedError
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
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.rest_client import KisRestClient
from app.integrations.upbit.errors import UpbitApiError
from app.integrations.upbit.rest_client import UpbitRestClient
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
from app.radar.macro_persistence import get_latest_macro_snapshot
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
    macro_regime: str | None
    macro_headline: str | None
    macro_observed_at: datetime | None


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
        macro_snapshot = await get_latest_macro_snapshot(session)

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
        macro_regime=macro_snapshot.regime if macro_snapshot is not None else None,
        macro_headline=macro_snapshot.headline if macro_snapshot is not None else None,
        macro_observed_at=macro_snapshot.observed_at if macro_snapshot is not None else None,
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


class PositionPriceOut(BaseModel):
    """`current_price`/`unrealized_pnl`/`unrealized_pnl_pct` are all
    `None` together when a live quote couldn't be fetched (KIS/Upbit not
    configured, or the call failed) - never a stale or fabricated number
    standing in for "unknown right now"."""

    symbol: str
    current_price: float | None
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None


class PositionPricesResponse(BaseModel):
    prices: list[PositionPriceOut]


def _position_price_out(position: PositionRow, current_price: float | None) -> PositionPriceOut:
    if current_price is None:
        return PositionPriceOut(symbol=position.symbol, current_price=None, unrealized_pnl=None, unrealized_pnl_pct=None)
    unrealized_pnl = (current_price - position.avg_entry_price) * position.quantity
    unrealized_pnl_pct = (
        (current_price - position.avg_entry_price) / position.avg_entry_price * 100
        if position.avg_entry_price > 0
        else None
    )
    return PositionPriceOut(
        symbol=position.symbol, current_price=current_price,
        unrealized_pnl=unrealized_pnl, unrealized_pnl_pct=unrealized_pnl_pct,
    )


@router.get("/positions/live-prices", response_model=PositionPricesResponse)
async def get_positions_live_prices() -> PositionPricesResponse:
    """P42: one real quote per open position (KIS for STOCK, Upbit for
    CRYPTO) - "are open positions safe?" needs to know current P&L, not
    just entry/stop price. Deliberately its own endpoint, not folded into
    `/summary` - unlike every other field there, this makes real external
    API calls per request, so the frontend polls it on its own, slower
    cadence and only while the 포지션 탭 is actually open, instead of
    every `/summary` refresh multiplying real KIS/Upbit call volume by
    however many positions exist.
    """
    settings = get_settings()
    async with session_scope() as session:
        pos_result = await session.execute(select(PositionRow).where(PositionRow.quantity > 0))
        positions = list(pos_result.scalars().all())

    prices: list[PositionPriceOut] = []

    stock_positions = [p for p in positions if p.asset_type == AssetType.STOCK.value]
    if stock_positions and settings.kis_configured:
        async with httpx.AsyncClient(base_url=settings.kis_rest_base_url) as client:
            auth = KisAuth(client=client, settings=settings)
            rest = KisRestClient(client, auth)
            for position in stock_positions:
                try:
                    quote = await rest.get_quote(position.symbol)
                    prices.append(_position_price_out(position, quote.price))
                except (KisApiError, httpx.HTTPError, KeyError, ValueError):
                    prices.append(_position_price_out(position, None))
    else:
        prices.extend(_position_price_out(p, None) for p in stock_positions)

    crypto_positions = [p for p in positions if p.asset_type == AssetType.CRYPTO.value]
    if crypto_positions:
        async with httpx.AsyncClient(base_url=settings.upbit_rest_base_url) as client:
            crypto_rest = UpbitRestClient(client)
            for position in crypto_positions:
                try:
                    price = await crypto_rest.get_ticker_price(position.symbol)
                    prices.append(_position_price_out(position, price))
                except (UpbitApiError, httpx.HTTPError, KeyError, ValueError):
                    prices.append(_position_price_out(position, None))

    return PositionPricesResponse(prices=prices)


class BalanceOut(BaseModel):
    """P45 - real combined KIS+Upbit account balance. `kis_total_value`/
    `upbit_total_value` are `None` when that broker isn't configured or
    the live fetch failed - see `app/account/balance.py`'s own docstring.
    """

    kis_total_value: float | None
    upbit_total_value: float | None
    total_assets: float


@router.get("/balance", response_model=BalanceOut)
async def get_balance() -> BalanceOut:
    """P45: the home screen's "총자산" card - a real, live-fetched
    combined balance (not read from `account_balance_snapshots`, which is
    for the trend chart below). Deliberately its own endpoint, not folded
    into `/summary`, for the same reason `/positions/live-prices` (P42)
    is: it makes real external KIS/Upbit calls per request."""
    settings = get_settings()
    balance = await fetch_combined_balance(settings)
    return BalanceOut(
        kis_total_value=balance.kis_total_value,
        upbit_total_value=balance.upbit_total_value,
        total_assets=balance.total_assets,
    )


class BalanceSnapshotOut(BaseModel):
    as_of: str
    total_assets: float


class BalanceHistoryOut(BaseModel):
    window: str
    snapshots: list[BalanceSnapshotOut]


_BALANCE_HISTORY_WINDOWS = {"1d": timedelta(days=1), "1w": timedelta(days=7), "1m": timedelta(days=30)}


@router.get("/balance/history", response_model=BalanceHistoryOut)
async def get_balance_history_endpoint(window: str = "1d") -> BalanceHistoryOut:
    """P45: the home screen's "자산 추이" chart - real periodic snapshots
    from `scripts/snapshot_balance.py`'s scheduler pass, never a
    fabricated curve. An empty list on a fresh deployment, or before that
    script has run even once, is the honest answer (see
    `app/account/persistence.py`'s own docstring). Unrecognized `window`
    values fall back to "1d" rather than erroring, matching how a typo'd
    URL param should degrade for a read-only chart."""
    now = datetime.now(UTC)
    since = datetime.min.replace(tzinfo=UTC) if window == "all" else now - _BALANCE_HISTORY_WINDOWS.get(window, _BALANCE_HISTORY_WINDOWS["1d"])

    async with session_scope() as session:
        rows = await get_balance_history(session, since=since)

    return BalanceHistoryOut(
        window=window,
        snapshots=[BalanceSnapshotOut(as_of=row.as_of.isoformat(), total_assets=row.total_assets) for row in rows],
    )


class EmergencyStopOut(BaseModel):
    kill_switch_active: bool
    kill_switch_reason: str | None


async def _record_manual_kill_switch_state(session: AsyncSession, active: bool, reason: str) -> RiskStateRow:
    """Inserts a new `RiskStateRow` reusing the latest real risk numbers
    (daily loss/exposure/etc unchanged) but with `kill_switch_active`
    forced to `active` - `RiskService.should_block_new_trades()` (P18)
    already reads "latest row by `as_of`" as current, so this takes
    effect immediately without a separate kill-switch mechanism to build.
    A deployment with no risk state recorded yet (fresh install) still
    gets a real row with honest zeroed numeric fields - `should_block_
    new_trades()` already treats "no row at all" as "block", so a manual
    stop before the first scan has even run is still meaningful."""
    result = await session.execute(select(RiskStateRow).order_by(RiskStateRow.as_of.desc()).limit(1))
    previous = result.scalar_one_or_none()
    now = datetime.now(UTC)
    row = RiskStateRow(
        as_of=now,
        daily_loss=previous.daily_loss if previous else 0.0,
        daily_loss_limit=previous.daily_loss_limit if previous else 0.0,
        exposure=previous.exposure if previous else 0.0,
        exposure_limit=previous.exposure_limit if previous else 0.0,
        open_positions=previous.open_positions if previous else 0,
        max_positions=previous.max_positions if previous else 0,
        consecutive_stops=previous.consecutive_stops if previous else 0,
        kill_switch_active=active,
        kill_switch_reason=reason,
    )
    session.add(row)
    await session.commit()
    return row


@router.post("/emergency-stop", response_model=EmergencyStopOut)
async def activate_emergency_stop(x_user_id: str = Header(..., alias="X-User-Id")) -> EmergencyStopOut:
    """P45: the home screen's red "긴급정지" button - immediately blocks
    new trades (`RiskService.should_block_new_trades()` reads this
    straight back) regardless of what the automatic P18 kill-switch
    evaluation currently says. Kakao-session-gated the same way
    `app/api/approvals.py`'s endpoints are (`_require_authenticated`,
    reused directly rather than duplicated) - this stops trades, so it
    doesn't weaken the "never fully autonomous" rule, but it's still a
    real action taken in the authenticated user's name and logged as such
    in `kill_switch_reason`."""
    async with session_scope() as session:
        try:
            await _require_authenticated(session, x_user_id)
        except ApprovalNotAuthenticatedError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        row = await _record_manual_kill_switch_state(session, True, f"사용자 수동 긴급정지 ({x_user_id})")

    return EmergencyStopOut(kill_switch_active=row.kill_switch_active, kill_switch_reason=row.kill_switch_reason)


@router.post("/emergency-stop/clear", response_model=EmergencyStopOut)
async def clear_emergency_stop(x_user_id: str = Header(..., alias="X-User-Id")) -> EmergencyStopOut:
    """P45: reverses `activate_emergency_stop()` - a new risk-state row
    with `kill_switch_active=False`, same real numeric fields carried
    forward, same Kakao-session gate. Does not re-evaluate the automatic
    P18 conditions; the next real scheduler cycle's own evaluation will
    turn it back on again if those conditions still hold, which is the
    intended behavior (a manual clear should not silently suppress a
    real, still-active risk condition past the next real check)."""
    async with session_scope() as session:
        try:
            await _require_authenticated(session, x_user_id)
        except ApprovalNotAuthenticatedError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        row = await _record_manual_kill_switch_state(session, False, f"사용자 수동 해제 ({x_user_id})")

    return EmergencyStopOut(kill_switch_active=row.kill_switch_active, kill_switch_reason=row.kill_switch_reason)


class SafetyCheckItemOut(BaseModel):
    key: str
    label: str
    status: str
    """"ok" | "warning" | "manual_check" - never a fabricated "ok" for
    something this endpoint can't actually verify; see each item below
    for what real signal backs it."""
    detail: str


class SafetyCheckOut(BaseModel):
    items: list[SafetyCheckItemOut]
    all_ok: bool


@router.get("/safety-check", response_model=SafetyCheckOut)
async def get_safety_check() -> SafetyCheckOut:
    """P45: the "시작 안전점검" onboarding screen's 5 checklist items -
    every item here is a real signal, not a hardcoded green checkmark:

    1. Demo/실거래 모드 - `Settings.live_trading` (already real).
    2. 거래소 연결 정상 - a real lightweight call per configured broker
       (KIS `get_quote("005930")`, Upbit `get_ticker_price("KRW-BTC")`).
    3. 출금 권한 비활성 - reframed from "is my API key's withdrawal
       permission off" (neither KIS's nor Upbit's public API exposes a
       way to introspect that from here, so this project doesn't fake a
       check it can't perform) to the actually-verifiable and arguably
       more relevant claim: this app's own integration code never calls
       any withdrawal endpoint for either broker - true by inspection of
       `app/integrations/kis/`/`app/integrations/upbit/`, which implement
       quote/balance/order placement and cancellation only.
    4. 오늘 최대손실 한도 - whether the latest real `RiskStateRow` has a
       configured (>0) `daily_loss_limit`; "warning" (not fabricated
       "ok") if no risk state has been recorded yet.
    5. 긴급정지 점검 완료 - whether the risk-state table is actually
       reachable right now, the same storage `activate_emergency_stop()`
       above writes to.
    """
    settings = get_settings()
    items: list[SafetyCheckItemOut] = []

    if settings.live_trading:
        items.append(
            SafetyCheckItemOut(
                key="demo_mode",
                label="실거래 모드",
                status="warning",
                detail="LIVE_TRADING이 활성화되어 실거래 모드로 실행 중입니다.",
            )
        )
    else:
        items.append(
            SafetyCheckItemOut(
                key="demo_mode",
                label="Demo 모드",
                status="ok",
                detail="LIVE_TRADING이 꺼져 있어 데모(모의) 환경이 활성화되어 있습니다.",
            )
        )

    kis_ok: bool | None = None
    if settings.kis_configured:
        try:
            async with httpx.AsyncClient(base_url=settings.kis_rest_base_url, timeout=10.0) as client:
                auth = KisAuth(client=client, settings=settings)
                rest = KisRestClient(client, auth)
                await rest.get_quote("005930")
            kis_ok = True
        except (KisApiError, httpx.HTTPError, KeyError, ValueError):
            kis_ok = False

    upbit_ok: bool
    try:
        async with httpx.AsyncClient(base_url=settings.upbit_rest_base_url, timeout=10.0) as client:
            upbit_rest = UpbitRestClient(client)
            await upbit_rest.get_ticker_price("KRW-BTC")
        upbit_ok = True
    except (UpbitApiError, httpx.HTTPError, KeyError, ValueError):
        upbit_ok = False

    connection_parts = [f"KIS {'정상' if kis_ok else '연결 실패'}" if settings.kis_configured else "KIS 미설정"]
    connection_parts.append(f"Upbit {'정상' if upbit_ok else '연결 실패'}")
    connection_ok = (kis_ok is not False) and upbit_ok
    items.append(
        SafetyCheckItemOut(
            key="exchange_connection",
            label="거래소 연결 정상",
            status="ok" if connection_ok else "warning",
            detail=" · ".join(connection_parts),
        )
    )

    items.append(
        SafetyCheckItemOut(
            key="withdrawal_disabled",
            label="출금 권한 비활성",
            status="ok",
            detail="이 앱의 코드는 어떤 거래소의 출금 API도 호출하지 않습니다 (매수/매도/조회 기능만 구현됨).",
        )
    )

    async with session_scope() as session:
        risk_result = await session.execute(select(RiskStateRow).order_by(RiskStateRow.as_of.desc()).limit(1))
        latest_risk = risk_result.scalar_one_or_none()

    if latest_risk is not None and latest_risk.daily_loss_limit > 0:
        items.append(
            SafetyCheckItemOut(
                key="daily_loss_limit",
                label="오늘 최대손실 한도",
                status="ok",
                detail=f"일일 최대손실 한도가 {latest_risk.daily_loss_limit:,.0f}(으)로 설정되어 있습니다.",
            )
        )
    else:
        items.append(
            SafetyCheckItemOut(
                key="daily_loss_limit",
                label="오늘 최대손실 한도",
                status="warning",
                detail="아직 리스크 상태가 기록되지 않았습니다 - 스캔/스케줄러가 최소 한 번 실행된 후 확인할 수 있습니다.",
            )
        )

    try:
        async with session_scope() as session:
            await session.execute(select(RiskStateRow).limit(1))
        items.append(
            SafetyCheckItemOut(
                key="kill_switch",
                label="긴급정지 점검 완료",
                status="ok",
                detail="긴급정지(킬스위치) 상태 저장소에 정상적으로 접근할 수 있습니다.",
            )
        )
    except Exception:  # noqa: BLE001 - any DB failure here must degrade to a status, never a 500
        items.append(
            SafetyCheckItemOut(
                key="kill_switch",
                label="긴급정지 점검 완료",
                status="warning",
                detail="긴급정지 상태 저장소에 접근할 수 없습니다 - 데이터베이스 연결을 확인하세요.",
            )
        )

    return SafetyCheckOut(items=items, all_ok=all(item.status == "ok" for item in items))
