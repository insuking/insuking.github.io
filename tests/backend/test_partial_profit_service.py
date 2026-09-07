"""P17 acceptance: PartialProfitService against the real local Postgres
(like test_guardian_service.py) - proving Position rows actually persist
the fill-derived state, not just the pure accounting math.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.db.models import Approval, Position, TradePlan
from app.db.models import Recommendation as RecommendationRow
from app.db.session import session_scope
from app.models.domain import PositionState
from app.partial_profit.accounting import FillEvent
from app.partial_profit.service import PartialProfitService

pytestmark = [pytest.mark.P17, pytest.mark.asyncio]

_TEST_SYMBOL = "KRW-PARTIAL-PROFIT-TEST"


def _fill(side: str, quantity: float, price: float, minute: int = 0) -> FillEvent:
    start = datetime(2026, 1, 5, tzinfo=UTC)
    return FillEvent(side=side, quantity=quantity, price=price, filled_at=start + timedelta(minutes=minute))


async def _make_position_and_plan(session) -> tuple[Position, TradePlan]:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    recommendation = RecommendationRow(
        id=f"rec-{now.timestamp()}",
        symbol=_TEST_SYMBOL,
        asset_type="CRYPTO",
        score=80.0,
        state="CONFIRMED_BREAKOUT",
        entry_low=100.0,
        entry_high=101.0,
        stop_price=90.0,
        t1_price=110.0,
        t1_percent=30.0,
        t2_price=120.0,
        t2_percent=30.0,
        runner_percent=40.0,
        expected_max_loss=1000.0,
        risk_reward=2.0,
        reasons="[]",
        risks="[]",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    session.add(recommendation)
    await session.commit()

    approval = Approval(
        id=f"appr-{now.timestamp()}",
        recommendation_id=recommendation.id,
        user_id="test-user-partial-profit",
        state="APPROVED",
        token_hash="deadbeef",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    session.add(approval)
    await session.commit()

    plan = TradePlan(
        id=f"plan-{now.timestamp()}",
        approval_id=approval.id,
        symbol=_TEST_SYMBOL,
        initial_qty=100.0,
        t1_percent=30.0,
        t2_percent=30.0,
        runner_percent=40.0,
        entry_price=100.0,
        stop_price=90.0,
        t1_price=110.0,
        t2_price=120.0,
    )
    position = Position(
        id=f"pos-{now.timestamp()}",
        symbol=_TEST_SYMBOL,
        asset_type="CRYPTO",
        quantity=100.0,
        avg_entry_price=100.0,
        stop_price=90.0,
        state="OPEN",
        guardian_active=True,
        opened_at=now,
        updated_at=now,
    )
    session.add(plan)
    session.add(position)
    await session.commit()
    return position, plan


@pytest.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(Position).where(Position.symbol == _TEST_SYMBOL))
        await session.execute(delete(TradePlan).where(TradePlan.symbol == _TEST_SYMBOL))
        recommendations = (
            await session.execute(
                select(RecommendationRow).where(RecommendationRow.symbol == _TEST_SYMBOL)
            )
        ).scalars().all()
        for recommendation in recommendations:
            await session.execute(delete(Approval).where(Approval.recommendation_id == recommendation.id))
        await session.execute(delete(RecommendationRow).where(RecommendationRow.symbol == _TEST_SYMBOL))
        await session.commit()


async def test_sync_position_partial_t1_fill_stays_open() -> None:
    async with session_scope() as session:
        position, plan = await _make_position_and_plan(session)
        service = PartialProfitService(session)

        fills = [_fill("BUY", 100, 100, minute=0), _fill("SELL", 15, 110, minute=1)]
        updated, accounting = await service.sync_position_from_fills(position, plan, fills)

    assert accounting.state == PositionState.OPEN
    assert updated.state == "OPEN"
    assert updated.quantity == 85


async def test_sync_position_full_t1_fill_persists_t1_filled_state() -> None:
    async with session_scope() as session:
        position, plan = await _make_position_and_plan(session)
        service = PartialProfitService(session)

        fills = [_fill("BUY", 100, 100, minute=0), _fill("SELL", 30, 110, minute=1)]
        _updated, accounting = await service.sync_position_from_fills(position, plan, fills)

        result = await session.execute(select(Position).where(Position.id == position.id))
        persisted = result.scalar_one()

    assert accounting.state == PositionState.T1_FILLED
    assert persisted.state == "T1_FILLED"
    assert persisted.quantity == 70


async def test_sync_position_updates_avg_entry_price_from_fills() -> None:
    async with session_scope() as session:
        position, plan = await _make_position_and_plan(session)
        service = PartialProfitService(session)

        fills = [_fill("BUY", 50, 100, minute=0), _fill("BUY", 50, 110, minute=1)]
        updated, _accounting = await service.sync_position_from_fills(position, plan, fills)

    assert updated.avg_entry_price == pytest.approx(105.0)


async def test_sync_position_full_exit_closes_position() -> None:
    async with session_scope() as session:
        position, plan = await _make_position_and_plan(session)
        service = PartialProfitService(session)

        fills = [_fill("BUY", 100, 100, minute=0), _fill("SELL", 100, 130, minute=1)]
        updated, accounting = await service.sync_position_from_fills(position, plan, fills)

    assert accounting.state == PositionState.CLOSED
    assert updated.state == "CLOSED"
    assert updated.quantity == 0
