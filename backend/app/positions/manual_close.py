"""Manual position close - real SELL market order (P46).

The gap this closes: nothing in this project could previously turn "the
user wants this position closed right now" into a real order. Guardian's
own automatic exits (`app/guardian/service.py`) are decision-only by
design - its own module docstring says turning a decision into a real
order is "the job of whatever process actually drives the tick", which
doesn't exist anywhere in this repository yet. This module is the first
thing that places a real SELL order against an existing `Position` row.

Broker-agnostic by construction, same shape as
`app/approval/execution.py`'s `execute_approved_recommendation()`: takes
an already-broker-wired `place_order` callable rather than importing a
specific provider, so `app/api/positions.py` wires KIS or Upbit by
`asset_type`, exactly like `app/api/approvals.py` already does for BUY
orders.

Quantity is always the position's full current `quantity` (whatever
`PartialProfitService` has already synced from real fills) - this is a
full liquidation, not a partial one; there is no partial-manual-close UI
in this project. Every mutating call underneath still goes through
`ExecutionProvider.place_order()`'s own `_require_live_trading()` gate -
this module adds no separate bypass and no separate live-trading check of
its own. If `place_order()` raises (e.g. `LiveTradingDisabledError`, a
broker error, `OrderTimeoutError`), it propagates to the caller with the
position left completely untouched - never a position marked CLOSED with
no real order behind it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order, Position, ProtectiveOrder

PlaceOrder = Callable[..., Awaitable[Order]]
BuildPlaceOrderKwargs = Callable[[float], dict[str, object]]


@dataclass
class ManualCloseResult:
    position: Position
    order: Order


async def close_position_market(
    session: AsyncSession,
    position: Position,
    place_order: PlaceOrder,
    build_place_order_kwargs: BuildPlaceOrderKwargs,
) -> ManualCloseResult:
    """Places one real market SELL order for `position`'s full current
    quantity, then marks the position `CLOSED` and deactivates its
    protective orders - only after the order call itself succeeds."""
    quantity = position.quantity
    order = await place_order(
        session,
        trade_plan_id=None,
        symbol=position.symbol,
        side="SELL",
        **build_place_order_kwargs(quantity),
    )

    position.quantity = 0.0
    position.state = "CLOSED"
    position.updated_at = datetime.now(UTC)

    protective_result = await session.execute(
        select(ProtectiveOrder).where(
            ProtectiveOrder.position_id == position.id, ProtectiveOrder.active.is_(True)
        )
    )
    for row in protective_result.scalars().all():
        row.active = False
        row.updated_at = datetime.now(UTC)

    await session.commit()
    return ManualCloseResult(position=position, order=order)
