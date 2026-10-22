"""P46 acceptance: `app/positions/manual_close.py`'s `close_position_market()`
- the first thing in this project that places a real SELL order against an
existing `Position`. Broker-agnostic by construction (same pattern as
`test_approval_execution.py`'s `execute_approved_recommendation()` tests),
so this is tested against real local Postgres rows with a fake in-memory
`place_order` callable rather than a real KIS/Upbit transport.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.models import Order, Position, ProtectiveOrder
from app.db.session import session_scope
from app.positions.manual_close import close_position_market

pytestmark = [pytest.mark.P46, pytest.mark.asyncio]

_TEST_SYMBOL = "MANUAL-CLOSE-TEST"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        positions = (await session.execute(select(Position).where(Position.symbol == _TEST_SYMBOL))).scalars().all()
        for position in positions:
            await session.execute(delete(ProtectiveOrder).where(ProtectiveOrder.position_id == position.id))
        await session.execute(delete(Position).where(Position.symbol == _TEST_SYMBOL))
        await session.execute(delete(Order).where(Order.symbol == _TEST_SYMBOL))
        await session.commit()


async def _make_position(session, quantity: float = 10.0) -> Position:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    position = Position(
        id=f"pos-{uuid.uuid4()}",
        symbol=_TEST_SYMBOL,
        asset_type="CRYPTO",
        quantity=quantity,
        avg_entry_price=100.0,
        stop_price=90.0,
        state="OPEN",
        guardian_active=True,
        opened_at=now,
        updated_at=now,
    )
    session.add(position)
    await session.commit()
    return position


def _fake_place_order(should_fail: bool = False) -> Callable[..., Awaitable[Order]]:
    async def place_order(
        session, *, trade_plan_id: str | None, symbol: str, side: str, **extra: object
    ) -> Order:
        if should_fail:
            raise RuntimeError("broker rejected the order")
        now = datetime.now(UTC)
        order = Order(
            id=str(uuid.uuid4()),
            trade_plan_id=trade_plan_id,
            symbol=symbol,
            side=side,
            order_type="MARKET",
            quantity=float(extra["quantity"]),  # type: ignore[arg-type]
            price=None,
            status="SUBMITTED",
            broker="FAKE",
            broker_order_id="FAKE-CLOSE-1",
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        await session.commit()
        return order

    return place_order


async def test_close_position_market_places_a_sell_order_for_the_full_quantity() -> None:
    async with session_scope() as session:
        position = await _make_position(session, quantity=10.0)

        result = await close_position_market(
            session, position, _fake_place_order(), lambda qty: {"quantity": str(qty)}
        )

    assert result.order.side == "SELL"
    assert result.order.quantity == 10.0
    assert result.position.state == "CLOSED"
    assert result.position.quantity == 0.0


async def test_close_position_market_deactivates_protective_orders() -> None:
    async with session_scope() as session:
        position = await _make_position(session)
        now = datetime.now(UTC)
        for kind, price in (("STOP", 90.0), ("T1", 110.0), ("T2", 120.0)):
            session.add(
                ProtectiveOrder(
                    id=f"po-{uuid.uuid4()}",
                    position_id=position.id,
                    kind=kind,
                    trigger_price=price,
                    quantity=3.0,
                    active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()

        await close_position_market(session, position, _fake_place_order(), lambda qty: {"quantity": str(qty)})

        remaining_active = (
            await session.execute(
                select(ProtectiveOrder).where(
                    ProtectiveOrder.position_id == position.id, ProtectiveOrder.active.is_(True)
                )
            )
        ).scalars().all()

    assert remaining_active == []


async def test_close_position_market_leaves_the_position_untouched_when_the_order_fails() -> None:
    async with session_scope() as session:
        position = await _make_position(session, quantity=10.0)

        with pytest.raises(RuntimeError):
            await close_position_market(
                session, position, _fake_place_order(should_fail=True), lambda qty: {"quantity": str(qty)}
            )

        result = await session.execute(select(Position).where(Position.id == position.id))
        persisted = result.scalar_one()

    assert persisted.state == "OPEN"
    assert persisted.quantity == 10.0
