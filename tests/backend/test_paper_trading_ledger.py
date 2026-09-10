"""P20 acceptance: ledger.py against the real local Postgres - cash and
position bookkeeping actually persist correctly across BUY/SELL, and the
long-only / affordability guards actually reject rather than silently
clamping.
"""

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.models import PaperAccount, PaperFill, PaperOrder, PaperPosition
from app.db.session import session_scope
from app.paper_trading.cost_model import TradingCosts
from app.paper_trading.fill_simulator import MarketSnapshot
from app.paper_trading.ledger import get_or_create_account, place_paper_order

pytestmark = [pytest.mark.P20, pytest.mark.asyncio]

_ACCOUNT_ID = "test-paper-ledger-account"
_MISSING_ACCOUNT_ID = "test-paper-ledger-account-missing"
_COSTS = TradingCosts(commission_rate=0.001, sell_tax_rate=0.002)
_SNAPSHOT = MarketSnapshot(bid=99.0, ask=101.0, available_volume=1000.0)


async def _get_position(session, symbol: str) -> PaperPosition:  # type: ignore[no-untyped-def]
    result = await session.execute(
        select(PaperPosition).where(PaperPosition.account_id == _ACCOUNT_ID, PaperPosition.symbol == symbol)
    )
    return result.scalar_one()


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        order_ids = (
            await session.execute(
                select(PaperOrder.id).where(PaperOrder.account_id == _ACCOUNT_ID)
            )
        ).scalars().all()
        if order_ids:
            await session.execute(delete(PaperFill).where(PaperFill.order_id.in_(order_ids)))
        await session.execute(delete(PaperOrder).where(PaperOrder.account_id == _ACCOUNT_ID))
        await session.execute(delete(PaperOrder).where(PaperOrder.account_id == _MISSING_ACCOUNT_ID))
        await session.execute(delete(PaperPosition).where(PaperPosition.account_id == _ACCOUNT_ID))
        await session.execute(delete(PaperAccount).where(PaperAccount.id == _ACCOUNT_ID))
        await session.commit()


async def test_get_or_create_account_creates_once_then_reuses() -> None:
    async with session_scope() as session:
        first = await get_or_create_account(session, _ACCOUNT_ID, "STOCK", starting_cash=1_000_000.0)
        second = await get_or_create_account(session, _ACCOUNT_ID, "STOCK", starting_cash=999.0)

    assert first.id == second.id
    assert second.cash_balance == 1_000_000.0  # not reset by the second call


async def test_market_buy_debits_cash_and_opens_a_position() -> None:
    async with session_scope() as session:
        await get_or_create_account(session, _ACCOUNT_ID, "STOCK", starting_cash=1_000_000.0)
        result = await place_paper_order(
            session,
            account_id=_ACCOUNT_ID,
            symbol="005930",
            side="BUY",
            order_type="MARKET",
            quantity=5.0,
            limit_price=None,
            snapshot=_SNAPSHOT,
            costs=_COSTS,
        )

    assert result.order.status == "FILLED"
    assert result.fill is not None
    assert result.fill.quantity == pytest.approx(5.0)
    assert result.fill.price >= _SNAPSHOT.ask

    async with session_scope() as session:
        account = await get_or_create_account(session, _ACCOUNT_ID, "STOCK", starting_cash=0.0)
        position = await _get_position(session, "005930")

    assert account.cash_balance < 1_000_000.0
    assert position.quantity == pytest.approx(5.0)


async def test_buy_rejected_when_cash_insufficient() -> None:
    async with session_scope() as session:
        await get_or_create_account(session, _ACCOUNT_ID, "STOCK", starting_cash=1.0)
        result = await place_paper_order(
            session,
            account_id=_ACCOUNT_ID,
            symbol="005930",
            side="BUY",
            order_type="MARKET",
            quantity=5.0,
            limit_price=None,
            snapshot=_SNAPSHOT,
            costs=_COSTS,
        )

    assert result.order.status == "REJECTED"
    assert result.fill is None
    assert result.order.rejection_reason is not None
    assert "cash" in result.order.rejection_reason


async def test_sell_rejected_when_no_position_held() -> None:
    async with session_scope() as session:
        await get_or_create_account(session, _ACCOUNT_ID, "STOCK", starting_cash=1_000_000.0)
        result = await place_paper_order(
            session,
            account_id=_ACCOUNT_ID,
            symbol="005930",
            side="SELL",
            order_type="MARKET",
            quantity=1.0,
            limit_price=None,
            snapshot=_SNAPSHOT,
            costs=_COSTS,
        )

    assert result.order.status == "REJECTED"
    assert result.order.rejection_reason is not None
    assert "position" in result.order.rejection_reason


async def test_sell_after_buy_credits_cash_and_reduces_position() -> None:
    async with session_scope() as session:
        await get_or_create_account(session, _ACCOUNT_ID, "STOCK", starting_cash=1_000_000.0)
        await place_paper_order(
            session,
            account_id=_ACCOUNT_ID,
            symbol="005930",
            side="BUY",
            order_type="MARKET",
            quantity=5.0,
            limit_price=None,
            snapshot=_SNAPSHOT,
            costs=_COSTS,
        )
        cash_after_buy = (
            await get_or_create_account(session, _ACCOUNT_ID, "STOCK", starting_cash=0.0)
        ).cash_balance

        result = await place_paper_order(
            session,
            account_id=_ACCOUNT_ID,
            symbol="005930",
            side="SELL",
            order_type="MARKET",
            quantity=5.0,
            limit_price=None,
            snapshot=_SNAPSHOT,
            costs=_COSTS,
        )

    assert result.order.status == "FILLED"
    assert result.fill is not None
    assert result.fill.tax > 0

    async with session_scope() as session:
        account = await get_or_create_account(session, _ACCOUNT_ID, "STOCK", starting_cash=0.0)
        position = await _get_position(session, "005930")

    assert account.cash_balance > cash_after_buy
    assert position.quantity == pytest.approx(0.0)


async def test_sell_more_than_held_is_rejected() -> None:
    async with session_scope() as session:
        await get_or_create_account(session, _ACCOUNT_ID, "STOCK", starting_cash=1_000_000.0)
        await place_paper_order(
            session,
            account_id=_ACCOUNT_ID,
            symbol="005930",
            side="BUY",
            order_type="MARKET",
            quantity=5.0,
            limit_price=None,
            snapshot=_SNAPSHOT,
            costs=_COSTS,
        )
        result = await place_paper_order(
            session,
            account_id=_ACCOUNT_ID,
            symbol="005930",
            side="SELL",
            order_type="MARKET",
            quantity=10.0,
            limit_price=None,
            snapshot=_SNAPSHOT,
            costs=_COSTS,
        )

    assert result.order.status == "REJECTED"


async def test_unmarketable_limit_buy_leaves_order_unfilled_without_touching_cash() -> None:
    async with session_scope() as session:
        await get_or_create_account(session, _ACCOUNT_ID, "STOCK", starting_cash=1_000_000.0)
        result = await place_paper_order(
            session,
            account_id=_ACCOUNT_ID,
            symbol="005930",
            side="BUY",
            order_type="LIMIT",
            quantity=5.0,
            limit_price=50.0,
            snapshot=_SNAPSHOT,
            costs=_COSTS,
        )
        account = await get_or_create_account(session, _ACCOUNT_ID, "STOCK", starting_cash=0.0)

    assert result.order.status == "REJECTED"
    assert result.fill is None
    assert account.cash_balance == 1_000_000.0


async def test_place_paper_order_rejects_unknown_account() -> None:
    async with session_scope() as session:
        result = await place_paper_order(
            session,
            account_id=_MISSING_ACCOUNT_ID,
            symbol="005930",
            side="BUY",
            order_type="MARKET",
            quantity=1.0,
            limit_price=None,
            snapshot=_SNAPSHOT,
            costs=_COSTS,
        )

    assert result.order.status == "REJECTED"
    assert result.order.rejection_reason is not None
    assert "no such paper account" in result.order.rejection_reason
