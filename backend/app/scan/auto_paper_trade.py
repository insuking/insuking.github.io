"""Connects the real crypto scan (P23) to the paper trading engine (P20) - P24.

Re-running this repeatedly (e.g. `scripts/paper_trade_crypto.py` on a
schedule) is the whole design: each run first checks every open paper
position against its stored exit plan and closes anything that has hit
its stop or target, then runs a fresh `scan_crypto_market()` and opens a
paper position for every Top-N recommendation not already held. The exit
rule is the same conservative "stop checked before target" order
`app/scan/crypto_backtest.py` validates historically - this module is
that same strategy, running forward on real, current prices instead of
history.

Explicitly simulated money, no human approval: P13/P14's approval flow
exists to gate *real* orders before they touch a broker, not paper ones -
see `app/paper_trading/ledger.py`'s own module docstring for the same
real/paper separation this respects.

What this does NOT do (documented, not hidden): P18's kill-switch/risk-
budget checks are not wired in here, so nothing stops this from opening
several positions in the same run beyond what `place_paper_order()`'s own
cash-affordability check rejects - a real auto-trading loop would need
P18 in front of it before ever touching a live account. T1/runner partial
exits and P16's trailing-stop tightening aren't modeled either, matching
`crypto_backtest.py`'s own documented scope (this validates the entry/exit
signal, not full position management).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PaperPosition
from app.integrations.upbit.rest_client import UpbitRestClient
from app.paper_trading.cost_model import costs_for_asset_type
from app.paper_trading.fill_simulator import MarketSnapshot
from app.paper_trading.ledger import get_or_create_account, place_paper_order
from app.paper_trading.replay_engine import DEFAULT_SPREAD_BPS
from app.scan.crypto_scan import TOP_N_RECOMMENDATIONS, scan_crypto_market

DEFAULT_STARTING_CASH = 10_000_000.0  # KRW placeholder - same convention as scripts/scan_crypto.py
_QUANTITY_TOLERANCE = 1e-9
_ASSET_TYPE = "CRYPTO"


@dataclass
class ClosedPosition:
    symbol: str
    exit_reason: str  # "STOP" | "TARGET"
    quantity: float
    exit_price: float


@dataclass
class OpenedPosition:
    symbol: str
    quantity: float
    entry_price: float
    stop_price: float
    t2_price: float


@dataclass
class SkippedRecommendation:
    symbol: str
    reason: str


@dataclass
class AutoPaperTradeReport:
    closed: list[ClosedPosition] = field(default_factory=list)
    opened: list[OpenedPosition] = field(default_factory=list)
    skipped: list[SkippedRecommendation] = field(default_factory=list)
    rejected_orders: list[str] = field(default_factory=list)


def _synthetic_snapshot(price: float, min_available_volume: float, spread_bps: float = DEFAULT_SPREAD_BPS) -> MarketSnapshot:
    """A bid/ask synthesized from a spread around the real last-trade price,
    with enough synthetic depth to avoid a partial fill - the same
    fallback `replay_engine.py` uses for plain OHLCV history, now applied
    to a live ticker price since neither carries real orderbook depth
    (P7's orderbook feed exists but isn't wired into this module)."""
    half_spread = price * (spread_bps / 10_000) / 2
    return MarketSnapshot(
        bid=price - half_spread, ask=price + half_spread, available_volume=min_available_volume * 10
    )


async def _get_open_positions(session: AsyncSession, account_id: str) -> list[PaperPosition]:
    result = await session.execute(
        select(PaperPosition).where(
            PaperPosition.account_id == account_id, PaperPosition.quantity > _QUANTITY_TOLERANCE
        )
    )
    return list(result.scalars().all())


def _check_exit(position: PaperPosition, current_price: float) -> str | None:
    if position.stop_price is not None and current_price <= position.stop_price:
        return "STOP"
    if position.t2_price is not None and current_price >= position.t2_price:
        return "TARGET"
    return None


async def run_auto_paper_trading(
    session: AsyncSession,
    rest: UpbitRestClient,
    account_id: str,
    starting_cash: float = DEFAULT_STARTING_CASH,
    top_n: int = TOP_N_RECOMMENDATIONS,
) -> AutoPaperTradeReport:
    report = AutoPaperTradeReport()
    await get_or_create_account(session, account_id, _ASSET_TYPE, starting_cash)
    costs = costs_for_asset_type(_ASSET_TYPE)
    closed_this_run: set[str] = set()

    for position in await _get_open_positions(session, account_id):
        current_price = await rest.get_ticker_price(position.symbol)
        exit_reason = _check_exit(position, current_price)
        if exit_reason is None:
            continue

        snapshot = _synthetic_snapshot(current_price, position.quantity)
        result = await place_paper_order(
            session,
            account_id=account_id,
            symbol=position.symbol,
            side="SELL",
            order_type="MARKET",
            quantity=position.quantity,
            limit_price=None,
            snapshot=snapshot,
            costs=costs,
        )
        if result.fill is not None:
            report.closed.append(ClosedPosition(position.symbol, exit_reason, result.fill.quantity, result.fill.price))
            closed_this_run.add(position.symbol)
        else:
            report.rejected_orders.append(f"{position.symbol}: SELL rejected - {result.order.rejection_reason}")

    account = await get_or_create_account(session, account_id, _ASSET_TYPE, starting_cash)
    held_symbols = {p.symbol for p in await _get_open_positions(session, account_id)}

    recommendations = await scan_crypto_market(rest, account_buying_power=account.cash_balance, top_n=top_n)
    for rec in recommendations:
        if rec.symbol in held_symbols:
            report.skipped.append(SkippedRecommendation(rec.symbol, "already holding a paper position"))
            continue
        if rec.symbol in closed_this_run:
            # Re-entry cooldown: a symbol just stopped/targeted out in this
            # same run is never immediately re-bought, even though it's no
            # longer "held" - without this, a fresh scan that still sees
            # the same live setup would whipsaw buy -> stop -> rebuy every
            # single run.
            report.skipped.append(SkippedRecommendation(rec.symbol, "closed earlier in this same run"))
            continue

        risk_per_unit = rec.entry_low - rec.stop_price
        if risk_per_unit <= 0:
            report.skipped.append(SkippedRecommendation(rec.symbol, "invalid risk setup"))
            continue
        quantity = rec.expected_max_loss / risk_per_unit

        snapshot = _synthetic_snapshot(rec.entry_low, quantity)
        result = await place_paper_order(
            session,
            account_id=account_id,
            symbol=rec.symbol,
            side="BUY",
            order_type="MARKET",
            quantity=quantity,
            limit_price=None,
            snapshot=snapshot,
            costs=costs,
        )
        if result.fill is None:
            report.rejected_orders.append(f"{rec.symbol}: BUY rejected - {result.order.rejection_reason}")
            continue

        position_result = await session.execute(
            select(PaperPosition).where(PaperPosition.account_id == account_id, PaperPosition.symbol == rec.symbol)
        )
        position = position_result.scalar_one()
        position.stop_price = rec.stop_price
        position.t2_price = rec.t2_price
        await session.commit()

        report.opened.append(
            OpenedPosition(rec.symbol, result.fill.quantity, result.fill.price, rec.stop_price, rec.t2_price)
        )

    return report
