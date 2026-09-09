"""Approval -> real execution bridge (P29).

The gap this closes: `ApprovalService.decide()` only ever produces an
APPROVED/REJECTED *decision* (see its own module docstring) - nothing in
this project previously called P14's `revalidate()` and then an actual
`ExecutionProvider` after a human approved something. That gap existed
for every broker (Toss/Upbit since P15, KIS since P29) - this module is
the first thing in this project that turns "a human approved this" into
"an order actually exists at a real broker", for any of them, not just
KIS. It's still deliberately narrow: it places one order and stops there.
Tracking that order to a real fill, and creating/opening a `Position`
from that fill, is not built here - `app/partial_profit/service.py`
already exists to sync `Position` state from `Fill` rows once fills are
tracked, but nothing yet polls a live broker for real fills the way
P20's paper-trading engine simulates them instantly. That's a real,
separate gap, not silently papered over by this module.

`execute_approved_recommendation()` is broker-agnostic by construction -
it takes an already-placed-order-capable callable
(`place_order: Callable[..., Awaitable[Order]]`, the exact shape every
`ExecutionProvider.place_order(session, *, trade_plan_id, symbol, side,
...)` in this project already has) rather than importing a specific
provider. `gather_kis_revalidation_input()` (STOCK -> KIS) and
`gather_upbit_revalidation_input()` (CRYPTO -> Upbit) below are the two
input-gathering helpers built so far, both feeding the same orchestrator.

**Toss is not wired in**, on purpose, not an oversight: `Recommendation.
asset_type` only distinguishes STOCK/CRYPTO (see `app/models/domain.py`'s
`AssetType`), but Toss Securities (P5/P15) and KIS (P3/P23+) are both
domestic-stock (KRX) brokers - nothing in this project's schema says which
one a given STOCK recommendation should route to, and the STOCK dispatch
in `app/api/approvals.py` was built assuming KIS (the broker the stock
radar itself was built against). Wiring Toss requires deciding that
routing question first, not just writing a third `gather_*` helper.

Quantity: reuses `app/recommendation/engine.py`'s own `position_size()`
formula against the recommendation's already-computed
`expected_max_loss`/`entry_low`/`stop_price` - the same numbers
`build_recommendation()` used to compute them in the first place, not a
fresh buying-power lookup. A live KIS buying-power endpoint is a real,
separate gap (this project has no verified one) - `revalidate()`'s own
`RiskState` exposure/daily-loss checks are the safety net standing in
for it here, not a substitute for actually re-checking cash on hand.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.approval.revalidation import (
    DEFAULT_THRESHOLDS,
    RevalidationInput,
    RevalidationThresholds,
    RevalidationVerdict,
    revalidate,
)
from app.approval.service import ApprovalService
from app.db.models import Approval, Order, Position, RiskStateRow, TradePlan
from app.db.models import Recommendation as RecommendationRow
from app.integrations.kis.rest_client import KOSPI_INDEX_CODE, KisRestClient
from app.integrations.upbit.rest_client import UpbitRestClient
from app.models.domain import Candle, RiskState
from app.recommendation.engine import position_size
from app.risk.state_store import latest_risk_state
from app.scan.crypto_scan import BENCHMARK_MARKET as UPBIT_BENCHMARK_MARKET
from app.scan.crypto_scan import CANDLE_COUNT as UPBIT_CANDLE_COUNT
from app.scan.crypto_scan import CANDLE_UNIT_MINUTES as UPBIT_CANDLE_UNIT_MINUTES

_BENCHMARK_HISTORY_DAYS = 90
_AVERAGE_VOLUME_WINDOW = 20


class ExecutionOutcome(str, Enum):
    EXECUTED = "EXECUTED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    NOT_APPROVED = "NOT_APPROVED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


@dataclass
class ExecutionResult:
    approval: Approval
    outcome: ExecutionOutcome
    order: Order | None = None
    trade_plan: TradePlan | None = None
    reasons: list[str] = field(default_factory=list)


PlaceOrder = Callable[..., Awaitable[Order]]
BuildPlaceOrderKwargs = Callable[[float], dict[str, object]]


async def execute_approved_recommendation(
    session: AsyncSession,
    approval: Approval,
    recommendation: RecommendationRow,
    revalidation_data: RevalidationInput,
    place_order: PlaceOrder,
    build_place_order_kwargs: BuildPlaceOrderKwargs,
    thresholds: RevalidationThresholds = DEFAULT_THRESHOLDS,
) -> ExecutionResult:
    """Re-checks an `APPROVED` approval one more time against
    `revalidation_data`, then places exactly one order if it's still
    valid. Never called for anything but an `APPROVED` approval - callers
    (e.g. `app/api/approvals.py`'s `decide` endpoint) call this right
    after `ApprovalService.decide()` returns one.

    `build_place_order_kwargs(quantity)`: this function computes
    `quantity` itself (see below) and hands it to the caller-supplied
    builder rather than making the caller pre-compute it - brokers don't
    even agree on what to call it in their own `place_order()` signature
    (Toss/KIS: `quantity`; Upbit: `volume`), so a plain kwargs dict built
    before this function runs would either duplicate the quantity
    calculation or hardcode one broker's field name here. The builder
    only needs to return whatever else that specific
    `ExecutionProvider.place_order()` requires beyond `trade_plan_id`/
    `symbol`/`side`, which this function already supplies.
    """
    approval_service = ApprovalService(session)

    if approval.state != "APPROVED":
        return ExecutionResult(
            approval, ExecutionOutcome.NOT_APPROVED, reasons=[f"approval state is {approval.state}, not APPROVED"]
        )

    report = revalidate(revalidation_data, thresholds)
    await approval_service.apply_revalidation_result(approval, report.verdict.value, report.reasons)
    if report.verdict != RevalidationVerdict.VALID:
        outcome = ExecutionOutcome(report.verdict.value)
        return ExecutionResult(approval, outcome, reasons=report.reasons)

    quantity = position_size(recommendation.expected_max_loss, recommendation.entry_low, recommendation.stop_price)
    if quantity <= 0:
        return ExecutionResult(
            approval,
            ExecutionOutcome.EXECUTION_FAILED,
            reasons=["computed order quantity is not positive - entry/stop prices leave no valid risk per unit"],
        )

    trade_plan = TradePlan(
        id=str(uuid.uuid4()),
        approval_id=approval.id,
        symbol=recommendation.symbol,
        initial_qty=quantity,
        t1_percent=recommendation.t1_percent,
        t2_percent=recommendation.t2_percent,
        runner_percent=recommendation.runner_percent,
        entry_price=recommendation.entry_low,
        stop_price=recommendation.stop_price,
        t1_price=recommendation.t1_price,
        t2_price=recommendation.t2_price,
    )
    session.add(trade_plan)
    await session.commit()

    try:
        extra_kwargs = build_place_order_kwargs(quantity)
        order = await place_order(
            session, trade_plan_id=trade_plan.id, symbol=recommendation.symbol, side="BUY", **extra_kwargs
        )
    except Exception as exc:  # noqa: BLE001 - any execution-provider failure must reach the caller as EXECUTION_FAILED, not crash the approval flow
        return ExecutionResult(approval, ExecutionOutcome.EXECUTION_FAILED, trade_plan=trade_plan, reasons=[repr(exc)])

    await approval_service.mark_executed(approval)
    return ExecutionResult(approval, ExecutionOutcome.EXECUTED, order=order, trade_plan=trade_plan)


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


async def gather_kis_revalidation_input(
    session: AsyncSession,
    rest: KisRestClient,
    approval: Approval,
    recommendation: RecommendationRow,
) -> RevalidationInput:
    """Assembles a real `RevalidationInput` for a KIS/stock recommendation
    right before executing it - a fresh quote, recent daily candles, the
    real KOSPI benchmark (all endpoints already verified real in P23/P25/
    P26), the latest recorded `RiskState`, and whether a position in this
    symbol is already open.

    `orderbook` stays `None`: this project has no verified KIS REST
    orderbook snapshot (P3's orderbook data is a WebSocket stream, not a
    one-shot lookup suited to this call) - `revalidate()` already treats
    a missing orderbook as "skip the spread/slippage checks", not a
    fabricated value, so leaving it unset is the honest choice.

    `market_data_healthy`/`broker_healthy` are both derived from whether
    the quote fetch below actually succeeded - a real, just-attempted KIS
    call succeeding is itself the health signal, rather than standing up
    a separate KIS-specific health check (P19's health_monitor covers
    DB/Redis/Guardian, not yet a per-broker API reachability check).
    """
    now = datetime.now(UTC)
    end_date = now.strftime("%Y%m%d")
    start_date = (now - timedelta(days=_BENCHMARK_HISTORY_DAYS)).strftime("%Y%m%d")

    try:
        quote = await rest.get_quote(recommendation.symbol)
        recent_candles = await rest.get_daily_prices(recommendation.symbol, start_date, end_date)
        benchmark_candles = await rest.get_index_daily_prices(KOSPI_INDEX_CODE, start_date, end_date)
        healthy = True
    except Exception:  # noqa: BLE001 - a failed live fetch must revalidate as unhealthy, not crash
        quote = None
        recent_candles = []
        benchmark_candles = []
        healthy = False

    average_volume = 0.0
    if len(recent_candles) > 1:
        window = recent_candles[-_AVERAGE_VOLUME_WINDOW - 1 : -1]
        if window:
            average_volume = sum(c.volume for c in window) / len(window)

    risk_row = await latest_risk_state(session)
    risk_state = _to_risk_state(risk_row) if risk_row is not None else None

    position_result = await session.execute(
        select(Position).where(Position.symbol == recommendation.symbol, Position.quantity > 0)
    )
    position_already_open = position_result.scalar_one_or_none() is not None

    return RevalidationInput(
        now=now,
        approval_expires_at=approval.expires_at,
        recommendation=recommendation,
        current_price=quote.price if quote is not None else 0.0,
        recent_candles=recent_candles,
        average_volume=average_volume,
        benchmark_candles=benchmark_candles,
        orderbook=None,
        risk_state=risk_state,
        market_data_healthy=healthy,
        broker_healthy=healthy,
        position_already_open=position_already_open,
    )


def _chronological(candles: list[Candle]) -> list[Candle]:
    """Upbit's REST candle endpoint returns most-recent-bar-first; every
    P4/P8 feature function (and `revalidate()` itself, via `recent_candles
    [-1]`) assumes ascending (oldest-first) order - same fact and fix as
    `app/scan/crypto_scan.py`'s own private `_chronological()`, kept as a
    tiny local copy rather than importing a same-module private helper
    across modules."""
    return list(reversed(candles))


async def gather_upbit_revalidation_input(
    session: AsyncSession,
    rest: UpbitRestClient,
    approval: Approval,
    recommendation: RecommendationRow,
) -> RevalidationInput:
    """Assembles a real `RevalidationInput` for a CRYPTO recommendation
    right before executing it via Upbit - a fresh ticker price, recent
    1-minute candles, the real KRW-BTC benchmark (all endpoints already
    verified real in P7/P9/P23's `app/scan/crypto_scan.py`), the latest
    recorded `RiskState`, and whether a position in this market is already
    open. Same shape and same honest gaps as `gather_kis_revalidation_input()`:

    `orderbook` stays `None`: `UpbitRestClient` (P7) has no orderbook
    snapshot method - Upbit's real-time orderbook only reaches this project
    over the WebSocket stream (`H0STASP0`-equivalent `orderbook` channel),
    not a one-shot REST call this function could make. `revalidate()`
    already treats a missing orderbook as "skip the spread/slippage
    checks", not a fabricated value.

    `market_data_healthy`/`broker_healthy` are both derived from whether
    the fetch below actually succeeded, same reasoning as KIS's version -
    P19's health_monitor doesn't yet expose a per-exchange REST reachability
    check to reuse instead.
    """
    now = datetime.now(UTC)

    try:
        current_price = await rest.get_ticker_price(recommendation.symbol)
        recent_candles = _chronological(
            await rest.get_candles(recommendation.symbol, UPBIT_CANDLE_UNIT_MINUTES, UPBIT_CANDLE_COUNT)
        )
        benchmark_candles = _chronological(
            await rest.get_candles(UPBIT_BENCHMARK_MARKET, UPBIT_CANDLE_UNIT_MINUTES, UPBIT_CANDLE_COUNT)
        )
        healthy = True
    except Exception:  # noqa: BLE001 - a failed live fetch must revalidate as unhealthy, not crash
        current_price = 0.0
        recent_candles = []
        benchmark_candles = []
        healthy = False

    average_volume = 0.0
    if len(recent_candles) > 1:
        window = recent_candles[-_AVERAGE_VOLUME_WINDOW - 1 : -1]
        if window:
            average_volume = sum(c.volume for c in window) / len(window)

    risk_row = await latest_risk_state(session)
    risk_state = _to_risk_state(risk_row) if risk_row is not None else None

    position_result = await session.execute(
        select(Position).where(Position.symbol == recommendation.symbol, Position.quantity > 0)
    )
    position_already_open = position_result.scalar_one_or_none() is not None

    return RevalidationInput(
        now=now,
        approval_expires_at=approval.expires_at,
        recommendation=recommendation,
        current_price=current_price,
        recent_candles=recent_candles,
        average_volume=average_volume,
        benchmark_candles=benchmark_candles,
        orderbook=None,
        risk_state=risk_state,
        market_data_healthy=healthy,
        broker_healthy=healthy,
        position_already_open=position_already_open,
    )
