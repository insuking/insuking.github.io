"""Paper trading ledger (P20): places a simulated order against a caller-
supplied `MarketSnapshot`, prices the fill (spread + slippage + partial
fill via `fill_simulator`, commission + tax via `cost_model`), and updates
the paper account's cash balance and position.

Long-only, like every real spot account this project ever trades on: a BUY
is rejected if the account can't afford the simulated notional + costs, and
a SELL is capped at the position's current quantity rather than allowed to
go negative (this ledger never simulates a short). Never touches `orders`/
`fills`/`positions` - see app/db/models.py's module docstring for why those
stay separate from `paper_orders`/`paper_fills`/`paper_positions`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PaperAccount, PaperFill, PaperOrder, PaperPosition
from app.paper_trading.cost_model import TradingCosts, calculate_commission, calculate_tax
from app.paper_trading.fill_simulator import MarketSnapshot, SimulatedFill, simulate_fill

_QUANTITY_TOLERANCE = 1e-9


@dataclass
class PaperTradeResult:
    order: PaperOrder
    fill: PaperFill | None


async def get_or_create_account(
    session: AsyncSession, account_id: str, asset_type: str, starting_cash: float
) -> PaperAccount:
    result = await session.execute(select(PaperAccount).where(PaperAccount.id == account_id))
    account = result.scalar_one_or_none()
    if account is not None:
        return account

    now = datetime.now(UTC)
    account = PaperAccount(
        id=account_id,
        asset_type=asset_type,
        cash_balance=starting_cash,
        created_at=now,
        updated_at=now,
    )
    session.add(account)
    await session.commit()
    return account


async def _get_position(session: AsyncSession, account_id: str, symbol: str) -> PaperPosition | None:
    result = await session.execute(
        select(PaperPosition).where(
            PaperPosition.account_id == account_id, PaperPosition.symbol == symbol
        )
    )
    return result.scalar_one_or_none()


async def _reject(session: AsyncSession, order: PaperOrder, reason: str) -> PaperTradeResult:
    order.status = "REJECTED"
    order.rejection_reason = reason
    order.updated_at = datetime.now(UTC)
    await session.commit()
    return PaperTradeResult(order=order, fill=None)


async def place_paper_order(
    session: AsyncSession,
    *,
    account_id: str,
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    limit_price: float | None,
    snapshot: MarketSnapshot,
    costs: TradingCosts,
    latency_ms: int = 0,
) -> PaperTradeResult:
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")

    # Looked up before the order row is created: `paper_orders.account_id`
    # has a foreign key to `paper_accounts`, so an order for a nonexistent
    # account must be rejected before insert, not after a constraint
    # violation.
    account_result = await session.execute(select(PaperAccount).where(PaperAccount.id == account_id))
    account = account_result.scalar_one_or_none()

    now = datetime.now(UTC)
    order = PaperOrder(
        id=str(uuid.uuid4()),
        account_id=account_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        status="PENDING",
        created_at=now,
        updated_at=now,
    )

    if account is None:
        # Not persisted: there is no valid account row for this order to
        # reference, and nothing durable needs to survive this rejection.
        order.status = "REJECTED"
        order.rejection_reason = f"no such paper account: {account_id}"
        return PaperTradeResult(order=order, fill=None)

    session.add(order)
    await session.commit()

    position = await _get_position(session, account_id, symbol)

    if side == "SELL":
        held = position.quantity if position is not None else 0.0
        if quantity > held + _QUANTITY_TOLERANCE:
            return await _reject(
                session, order, f"insufficient paper position: held={held}, requested={quantity}"
            )

    simulated: SimulatedFill = simulate_fill(
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        snapshot=snapshot,
        latency_ms=latency_ms,
    )

    if simulated.fill_quantity <= 0:
        order.status = "REJECTED" if not simulated.partial else "UNFILLED"
        order.rejection_reason = "not marketable" if order_type == "LIMIT" else "no liquidity available"
        order.updated_at = datetime.now(UTC)
        await session.commit()
        return PaperTradeResult(order=order, fill=None)

    notional = simulated.fill_quantity * simulated.fill_price
    commission = calculate_commission(notional, costs)
    tax = calculate_tax(notional, side, costs)

    if side == "BUY":
        cash_required = notional + commission
        if cash_required > account.cash_balance + _QUANTITY_TOLERANCE:
            return await _reject(
                session,
                order,
                f"insufficient paper cash: available={account.cash_balance}, required={cash_required}",
            )
        account.cash_balance -= cash_required

        if position is None:
            position = PaperPosition(
                id=str(uuid.uuid4()),
                account_id=account_id,
                symbol=symbol,
                quantity=simulated.fill_quantity,
                avg_entry_price=simulated.fill_price,
                updated_at=now,
            )
            session.add(position)
        else:
            total_cost = position.quantity * position.avg_entry_price + notional
            position.quantity += simulated.fill_quantity
            position.avg_entry_price = total_cost / position.quantity
            position.updated_at = now
    else:
        account.cash_balance += notional - commission - tax
        assert position is not None
        position.quantity -= simulated.fill_quantity
        position.updated_at = now

    account.updated_at = now
    order.status = "PARTIALLY_FILLED" if simulated.partial else "FILLED"
    order.updated_at = now

    fill = PaperFill(
        id=str(uuid.uuid4()),
        order_id=order.id,
        quantity=simulated.fill_quantity,
        price=simulated.fill_price,
        slippage_amount=simulated.slippage_amount,
        commission=commission,
        tax=tax,
        latency_ms=simulated.latency_ms,
        filled_at=now,
    )
    session.add(fill)
    await session.commit()

    return PaperTradeResult(order=order, fill=fill)
