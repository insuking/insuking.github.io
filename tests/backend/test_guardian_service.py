"""P16 acceptance: PositionGuardianService against the real local Postgres
(like test_approval_service.py) - what's being proven is that protective
order rows and position state actually persist correctly.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.db.models import Approval, Position, ProtectiveOrder, TradePlan
from app.db.models import Recommendation as RecommendationRow
from app.db.session import session_scope
from app.guardian.service import GuardianActionType, PositionGuardianService
from app.models.domain import Candle, PositionState
from app.radar.state import RadarState

pytestmark = [pytest.mark.P16, pytest.mark.asyncio]

_TEST_SYMBOL = "KRW-GUARDIAN-TEST"


def _candle(close: float, minute: int) -> Candle:
    start = datetime(2026, 1, 5, tzinfo=UTC) + timedelta(minutes=minute)
    return Candle(
        symbol=_TEST_SYMBOL,
        interval="1m",
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=10,
        open_time=start,
        close_time=start + timedelta(minutes=1),
    )


def _flat_candles(count: int, price: float = 100.0) -> list[Candle]:
    """A flat series: true range stays constant and small, so the ATR
    trailing candidate sits comfortably below any reasonable current stop -
    i.e. a scenario that must NOT tighten."""
    return [_candle(price, minute=i) for i in range(count)]


def _rising_candles(count: int, start_price: float = 100.0) -> list[Candle]:
    return [_candle(start_price + i, minute=i) for i in range(count)]


async def _make_position_and_plan(session, **position_overrides: object) -> tuple[Position, TradePlan]:  # type: ignore[no-untyped-def]
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
    approval = Approval(
        id=f"appr-{now.timestamp()}",
        recommendation_id=recommendation.id,
        user_id="test-user-guardian",
        state="APPROVED",
        token_hash="deadbeef",
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    session.add(recommendation)
    await session.commit()
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
    position_defaults: dict[str, object] = {
        "id": f"pos-{now.timestamp()}",
        "symbol": _TEST_SYMBOL,
        "asset_type": "CRYPTO",
        "quantity": 100.0,
        "avg_entry_price": 100.0,
        "stop_price": 90.0,
        "state": "OPEN",
        "guardian_active": True,
        "opened_at": now,
        "updated_at": now,
    }
    position_defaults.update(position_overrides)
    position = Position(**position_defaults)
    session.add(plan)
    session.add(position)
    await session.commit()
    return position, plan


@pytest.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        positions = (
            await session.execute(select(Position).where(Position.symbol == _TEST_SYMBOL))
        ).scalars().all()
        for position in positions:
            await session.execute(
                delete(ProtectiveOrder).where(ProtectiveOrder.position_id == position.id)
            )
        await session.execute(delete(Position).where(Position.symbol == _TEST_SYMBOL))
        await session.execute(delete(TradePlan).where(TradePlan.symbol == _TEST_SYMBOL))
        recommendations = (
            await session.execute(
                select(RecommendationRow).where(RecommendationRow.symbol == _TEST_SYMBOL)
            )
        ).scalars().all()
        for recommendation in recommendations:
            await session.execute(
                delete(Approval).where(Approval.recommendation_id == recommendation.id)
            )
        await session.execute(delete(RecommendationRow).where(RecommendationRow.symbol == _TEST_SYMBOL))
        await session.commit()


async def test_ensure_initial_orders_creates_stop_t1_t2() -> None:
    async with session_scope() as session:
        position, plan = await _make_position_and_plan(session)
        service = PositionGuardianService(session)

        rows = await service.ensure_initial_orders(position, plan)

    kinds = sorted(row.kind for row in rows)
    assert kinds == ["STOP", "T1", "T2"]


async def test_ensure_initial_orders_is_idempotent() -> None:
    async with session_scope() as session:
        position, plan = await _make_position_and_plan(session)
        service = PositionGuardianService(session)

        first = await service.ensure_initial_orders(position, plan)
        second = await service.ensure_initial_orders(position, plan)

    assert len(first) == 3
    assert {row.id for row in second} == {row.id for row in first}


async def test_process_position_skips_when_guardian_inactive() -> None:
    async with session_scope() as session:
        position, plan = await _make_position_and_plan(session, guardian_active=False)
        service = PositionGuardianService(session)
        await service.ensure_initial_orders(position, plan)

        action = await service.process_position(
            position, RadarState.FAILED_BREAKOUT, _flat_candles(20)
        )

    assert action.action == GuardianActionType.GUARDIAN_INACTIVE
    assert position.state == "OPEN"  # untouched


async def test_process_position_exits_on_failed_breakout_while_open() -> None:
    async with session_scope() as session:
        position, plan = await _make_position_and_plan(session, state=PositionState.OPEN.value)
        service = PositionGuardianService(session)
        await service.ensure_initial_orders(position, plan)

        action = await service.process_position(position, RadarState.FAILED_BREAKOUT, _flat_candles(20))

        orders = (
            await session.execute(
                select(ProtectiveOrder).where(ProtectiveOrder.position_id == position.id)
            )
        ).scalars().all()

    assert action.action == GuardianActionType.EXIT_FAILED_BREAKOUT
    assert position.state == PositionState.CLOSED.value
    assert all(not row.active for row in orders)


async def test_process_position_does_not_exit_on_failed_breakout_once_past_open() -> None:
    async with session_scope() as session:
        position, plan = await _make_position_and_plan(session, state=PositionState.T1_FILLED.value)
        service = PositionGuardianService(session)
        await service.ensure_initial_orders(position, plan)

        action = await service.process_position(position, RadarState.FAILED_BREAKOUT, _flat_candles(20))

    assert action.action != GuardianActionType.EXIT_FAILED_BREAKOUT
    assert position.state == PositionState.T1_FILLED.value


async def test_process_position_reports_no_active_stop_when_none_exists() -> None:
    async with session_scope() as session:
        position, _plan = await _make_position_and_plan(session)
        service = PositionGuardianService(session)
        # deliberately skip ensure_initial_orders

        action = await service.process_position(position, RadarState.CONFIRMED_BREAKOUT, _flat_candles(20))

    assert action.action == GuardianActionType.NO_ACTIVE_STOP


async def test_process_position_tightens_stop_when_trailing_candidate_is_higher() -> None:
    async with session_scope() as session:
        position, plan = await _make_position_and_plan(session)
        service = PositionGuardianService(session)
        await service.ensure_initial_orders(position, plan)

        # A strong rise pushes the ATR trailing candidate well above the
        # original 90.0 stop.
        action = await service.process_position(
            position, RadarState.CONFIRMED_BREAKOUT, _rising_candles(20, start_price=100.0)
        )

        stop_order = (
            await session.execute(
                select(ProtectiveOrder).where(
                    ProtectiveOrder.position_id == position.id, ProtectiveOrder.kind == "STOP"
                )
            )
        ).scalar_one()

    assert action.action == GuardianActionType.TIGHTENED_STOP
    assert stop_order.trigger_price > 90.0
    assert position.stop_price == stop_order.trigger_price


async def test_process_position_leaves_stop_unchanged_when_not_tighter() -> None:
    async with session_scope() as session:
        position, plan = await _make_position_and_plan(session)
        service = PositionGuardianService(session)
        await service.ensure_initial_orders(position, plan)

        action = await service.process_position(
            position, RadarState.CONFIRMED_BREAKOUT, _flat_candles(20, price=91.0)
        )

    assert action.action == GuardianActionType.OK
    assert position.stop_price == 90.0
