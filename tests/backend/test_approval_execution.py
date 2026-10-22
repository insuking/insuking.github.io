"""P29 acceptance: the approval -> execution bridge
(app/approval/execution.py) - the piece that turns an APPROVED approval
into a real order via `execute_approved_recommendation()`, plus KIS's
concrete `gather_kis_revalidation_input()`.

Real local Postgres for Approval/Recommendation/TradePlan/Order/RiskStateRow/
Position (same DB-backed pattern as test_approvals_api.py/
test_kis_execution.py); `execute_approved_recommendation()` itself is
broker-agnostic so it's tested with a fake in-memory `place_order` callable
rather than a real KIS transport. `gather_kis_revalidation_input()` is
tested separately against a mocked KIS transport (httpx.MockTransport,
never a real connection) since it's the one KIS-specific piece.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from app.approval.execution import (
    ExecutionOutcome,
    execute_approved_recommendation,
    gather_kis_revalidation_input,
    gather_upbit_revalidation_input,
)
from app.approval.revalidation import RevalidationInput
from app.approval.service import ApprovalService
from app.core.config import Settings
from app.db.models import Approval, Order, Position, RiskStateRow
from app.db.models import Recommendation as RecommendationRow
from app.db.session import session_scope
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.rest_client import KisRestClient
from app.integrations.upbit.rest_client import UpbitRestClient
from sqlalchemy import delete, select

pytestmark = [pytest.mark.P29, pytest.mark.asyncio]

_TEST_USER_ID = "test-user-approval-execution"
_TEST_SYMBOL = "APPREXEC-TEST"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    """`@pytest_asyncio.fixture` (not plain `@pytest.fixture`) - matching
    `tests/backend/conftest.py`'s own `_reset_connection_singletons`
    pattern, not a stylistic choice: in this project's pinned
    pytest-asyncio version, `asyncio_mode = auto` does not reliably drive a
    plain `@pytest.fixture` async generator's teardown, so an autouse
    cleanup declared that way can silently never run its `yield`-after
    code, leaking rows across test runs."""
    yield
    async with session_scope() as session:
        await session.execute(delete(Order).where(Order.symbol == _TEST_SYMBOL))
        approvals = (
            (await session.execute(select(Approval).where(Approval.user_id == _TEST_USER_ID))).scalars().all()
        )
        from app.db.models import ApprovalEvent, TradePlan

        for approval in approvals:
            await session.execute(delete(TradePlan).where(TradePlan.approval_id == approval.id))
            await session.execute(delete(ApprovalEvent).where(ApprovalEvent.approval_id == approval.id))
        await session.execute(delete(Approval).where(Approval.user_id == _TEST_USER_ID))
        await session.execute(delete(RecommendationRow).where(RecommendationRow.symbol == _TEST_SYMBOL))
        await session.execute(delete(Position).where(Position.symbol == _TEST_SYMBOL))
        await session.execute(
            delete(RiskStateRow).where(RiskStateRow.kill_switch_reason == "test kill switch")
        )
        await session.commit()


async def _create_approved(
    *, entry_low: float = 1000.0, stop_price: float = 900.0, expected_max_loss: float = 1000.0
) -> tuple[Approval, RecommendationRow]:
    now = datetime.now(UTC)
    async with session_scope() as session:
        rec = RecommendationRow(
            id=f"rec-{uuid.uuid4()}",
            symbol=_TEST_SYMBOL,
            asset_type="STOCK",
            score=88.0,
            state="CONFIRMED_BREAKOUT",
            entry_low=entry_low,
            entry_high=entry_low + 20.0,
            stop_price=stop_price,
            t1_price=entry_low + 100.0,
            t1_percent=30.0,
            t2_price=entry_low + 200.0,
            t2_percent=30.0,
            runner_percent=40.0,
            expected_max_loss=expected_max_loss,
            risk_reward=2.0,
            reasons="[]",
            risks="[]",
            created_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        session.add(rec)
        await session.commit()

        service = ApprovalService(session)
        approval, _plaintext = await service.create_approval(rec.id, _TEST_USER_ID)
        approval.state = "APPROVED"
        await session.commit()
        await session.refresh(approval)
        await session.refresh(rec)
        return approval, rec


def _valid_revalidation_input(approval: Approval, rec: RecommendationRow) -> RevalidationInput:
    return RevalidationInput(
        now=datetime.now(UTC),
        approval_expires_at=approval.expires_at,
        recommendation=rec,
        current_price=rec.entry_low,
        market_data_healthy=True,
        broker_healthy=True,
        position_already_open=False,
    )


def _fake_place_order(order_status: str = "SUBMITTED") -> Callable[..., Awaitable[Order]]:
    async def place_order(
        session, *, trade_plan_id: str | None, symbol: str, side: str, **extra: object
    ) -> Order:
        now = datetime.now(UTC)
        order = Order(
            id=str(uuid.uuid4()),
            trade_plan_id=trade_plan_id,
            symbol=symbol,
            side=side,
            order_type="LIMIT",
            quantity=float(extra["quantity"]),  # type: ignore[arg-type]
            price=float(extra["price"]) if extra.get("price") is not None else None,  # type: ignore[arg-type]
            status=order_status,
            broker="FAKE",
            broker_order_id="FAKE-1",
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        await session.commit()
        return order

    return place_order


def _kwargs_builder(quantity: float) -> dict[str, object]:
    return {"quantity": str(quantity), "price": "1000"}


# --- execute_approved_recommendation ----------------------------------------


async def test_execute_returns_not_approved_for_non_approved_state() -> None:
    approval, rec = await _create_approved()
    async with session_scope() as session:
        approval.state = "REJECTED"
        await session.commit()
        result = await execute_approved_recommendation(
            session, approval, rec, _valid_revalidation_input(approval, rec), _fake_place_order(), _kwargs_builder
        )
    assert result.outcome == ExecutionOutcome.NOT_APPROVED
    assert result.order is None


async def test_execute_invalidates_and_never_places_order_on_stale_price() -> None:
    approval, rec = await _create_approved(entry_low=1000.0, stop_price=900.0)
    async with session_scope() as session:
        # Re-fetch approval through *this* session rather than reusing the
        # detached instance `_create_approved()` returned (its own
        # session_scope() already closed) - otherwise `mark_executed()`/
        # `apply_revalidation_result()`'s mutation never gets flushed:
        # SQLAlchemy only tracks attached, session-identity-mapped objects
        # as dirty, exactly like the real `decide_approval()` endpoint
        # passes an approval it already loaded through the same session.
        approval = await session.get(Approval, approval.id)
        data = _valid_revalidation_input(approval, rec)
        data.current_price = 850.0  # already through the stop
        result = await execute_approved_recommendation(
            session, approval, rec, data, _fake_place_order(), _kwargs_builder
        )

    assert result.outcome == ExecutionOutcome.INVALIDATED
    assert result.order is None
    assert result.reasons

    async with session_scope() as session:
        refreshed = (await session.execute(select(Approval).where(Approval.id == approval.id))).scalar_one()
        assert refreshed.state == "INVALIDATED"


async def test_execute_returns_expired_when_approval_ttl_elapsed() -> None:
    approval, rec = await _create_approved()
    async with session_scope() as session:
        data = _valid_revalidation_input(approval, rec)
        data.now = approval.expires_at + timedelta(seconds=1)
        result = await execute_approved_recommendation(
            session, approval, rec, data, _fake_place_order(), _kwargs_builder
        )
    assert result.outcome == ExecutionOutcome.EXPIRED
    assert result.order is None


async def test_execute_fails_when_quantity_not_positive() -> None:
    # entry_low == stop_price -> position_size()'s per-unit-risk is 0, so
    # quantity comes out non-positive. current_price is set to entry_high
    # (not the helper's default of entry_low, which here equals stop_price
    # and would trip revalidate()'s own "price fell through the stop"
    # check before ever reaching the quantity guard this test targets).
    approval, rec = await _create_approved(entry_low=1000.0, stop_price=1000.0, expected_max_loss=1000.0)
    async with session_scope() as session:
        approval = await session.get(Approval, approval.id)
        data = _valid_revalidation_input(approval, rec)
        data.current_price = rec.entry_high
        result = await execute_approved_recommendation(
            session, approval, rec, data, _fake_place_order(), _kwargs_builder
        )
    assert result.outcome == ExecutionOutcome.EXECUTION_FAILED
    assert result.order is None
    assert "quantity" in result.reasons[0]


async def test_execute_fails_when_place_order_raises() -> None:
    approval, rec = await _create_approved()

    async def failing_place_order(session, **kwargs: object) -> Order:
        raise RuntimeError("broker unreachable")

    async with session_scope() as session:
        data = _valid_revalidation_input(approval, rec)
        result = await execute_approved_recommendation(
            session, approval, rec, data, failing_place_order, _kwargs_builder
        )

    assert result.outcome == ExecutionOutcome.EXECUTION_FAILED
    assert result.trade_plan is not None
    assert "broker unreachable" in result.reasons[0]

    async with session_scope() as session:
        refreshed = (await session.execute(select(Approval).where(Approval.id == approval.id))).scalar_one()
        assert refreshed.state == "APPROVED"  # still APPROVED - place_order failure doesn't mark EXECUTED


async def test_execute_success_marks_executed_and_creates_trade_plan_and_order() -> None:
    approval, rec = await _create_approved()
    async with session_scope() as session:
        approval = await session.get(Approval, approval.id)
        data = _valid_revalidation_input(approval, rec)
        result = await execute_approved_recommendation(
            session, approval, rec, data, _fake_place_order(), _kwargs_builder
        )

    assert result.outcome == ExecutionOutcome.EXECUTED
    assert result.order is not None
    assert result.order.status == "SUBMITTED"
    assert result.trade_plan is not None
    assert result.trade_plan.symbol == _TEST_SYMBOL

    async with session_scope() as session:
        refreshed = (await session.execute(select(Approval).where(Approval.id == approval.id))).scalar_one()
        assert refreshed.state == "EXECUTED"


# --- gather_kis_revalidation_input -------------------------------------------


def _settings() -> Settings:
    return Settings(kis_app_key="k", kis_app_secret="s")  # type: ignore[call-arg]


def _rest_client_with(handler: Callable[[httpx.Request], httpx.Response]) -> KisRestClient:
    def full_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(full_handler), base_url="https://mock.kis.test")
    auth = KisAuth(client=client, settings=_settings())
    return KisRestClient(client, auth)


async def test_gather_kis_revalidation_input_healthy_on_success() -> None:
    approval, rec = await _create_approved()

    def handler(request: httpx.Request) -> httpx.Response:
        if "inquire-price" in request.url.path:
            return httpx.Response(200, json={"rt_cd": "0", "output": {"stck_prpr": "1010", "acml_vol": "1000"}})
        if "indexchartprice" in request.url.path:
            return httpx.Response(200, json={"rt_cd": "0", "output2": []})
        if "itemchartprice" in request.url.path:
            return httpx.Response(200, json={"rt_cd": "0", "output1": {}, "output2": []})
        raise AssertionError(f"unexpected path {request.url.path}")

    rest = _rest_client_with(handler)
    async with session_scope() as session:
        data = await gather_kis_revalidation_input(session, rest, approval, rec)

    assert data.market_data_healthy is True
    assert data.broker_healthy is True
    assert data.current_price == 1010.0
    assert data.position_already_open is False


async def test_gather_kis_revalidation_input_unhealthy_on_fetch_failure() -> None:
    approval, rec = await _create_approved()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"rt_cd": "1", "msg1": "boom"})

    rest = _rest_client_with(handler)
    async with session_scope() as session:
        data = await gather_kis_revalidation_input(session, rest, approval, rec)

    assert data.market_data_healthy is False
    assert data.broker_healthy is False
    assert data.current_price == 0.0


async def test_gather_kis_revalidation_input_detects_open_position() -> None:
    approval, rec = await _create_approved()
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            Position(
                id=f"pos-{uuid.uuid4()}",
                symbol=_TEST_SYMBOL,
                asset_type="STOCK",
                quantity=10.0,
                avg_entry_price=1000.0,
                stop_price=900.0,
                state="OPEN",
                opened_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if "inquire-price" in request.url.path:
            return httpx.Response(200, json={"rt_cd": "0", "output": {"stck_prpr": "1010", "acml_vol": "1000"}})
        return httpx.Response(200, json={"rt_cd": "0", "output1": {}, "output2": []})

    rest = _rest_client_with(handler)
    async with session_scope() as session:
        data = await gather_kis_revalidation_input(session, rest, approval, rec)

    assert data.position_already_open is True


async def test_gather_kis_revalidation_input_uses_latest_risk_state() -> None:
    approval, rec = await _create_approved()
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            RiskStateRow(
                id=f"risk-{uuid.uuid4()}",
                as_of=now,
                daily_loss=0.0,
                daily_loss_limit=1000.0,
                exposure=0.0,
                exposure_limit=1000.0,
                open_positions=0,
                max_positions=5,
                consecutive_stops=0,
                kill_switch_active=True,
                kill_switch_reason="test kill switch",
            )
        )
        await session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if "inquire-price" in request.url.path:
            return httpx.Response(200, json={"rt_cd": "0", "output": {"stck_prpr": "1010", "acml_vol": "1000"}})
        return httpx.Response(200, json={"rt_cd": "0", "output1": {}, "output2": []})

    rest = _rest_client_with(handler)
    async with session_scope() as session:
        data = await gather_kis_revalidation_input(session, rest, approval, rec)

    assert data.risk_state is not None
    assert data.risk_state.kill_switch_active is True
    assert data.risk_state.kill_switch_reason == "test kill switch"


# --- gather_upbit_revalidation_input -----------------------------------------


def _upbit_rest_client_with(handler: Callable[[httpx.Request], httpx.Response]) -> UpbitRestClient:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.upbit.test")
    return UpbitRestClient(client)


def _upbit_handler(ticker_price: str = "710.0") -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/ticker":
            return httpx.Response(200, json=[{"market": _TEST_SYMBOL, "trade_price": ticker_price}])
        if request.url.path.startswith("/v1/candles/minutes/"):
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected path {request.url.path}")

    return handler


async def test_gather_upbit_revalidation_input_healthy_on_success() -> None:
    approval, rec = await _create_approved()

    rest = _upbit_rest_client_with(_upbit_handler(ticker_price="710.0"))
    async with session_scope() as session:
        data = await gather_upbit_revalidation_input(session, rest, approval, rec)

    assert data.market_data_healthy is True
    assert data.broker_healthy is True
    assert data.current_price == 710.0
    assert data.position_already_open is False


async def test_gather_upbit_revalidation_input_unhealthy_on_fetch_failure() -> None:
    approval, rec = await _create_approved()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"name": "boom", "message": "boom"}})

    rest = _upbit_rest_client_with(handler)
    async with session_scope() as session:
        data = await gather_upbit_revalidation_input(session, rest, approval, rec)

    assert data.market_data_healthy is False
    assert data.broker_healthy is False
    assert data.current_price == 0.0


async def test_gather_upbit_revalidation_input_detects_open_position() -> None:
    approval, rec = await _create_approved()
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            Position(
                id=f"pos-{uuid.uuid4()}",
                symbol=_TEST_SYMBOL,
                asset_type="CRYPTO",
                quantity=10.0,
                avg_entry_price=700.0,
                stop_price=650.0,
                state="OPEN",
                opened_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    rest = _upbit_rest_client_with(_upbit_handler())
    async with session_scope() as session:
        data = await gather_upbit_revalidation_input(session, rest, approval, rec)

    assert data.position_already_open is True


async def test_gather_upbit_revalidation_input_uses_latest_risk_state() -> None:
    approval, rec = await _create_approved()
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            RiskStateRow(
                id=f"risk-{uuid.uuid4()}",
                as_of=now,
                daily_loss=0.0,
                daily_loss_limit=1000.0,
                exposure=0.0,
                exposure_limit=1000.0,
                open_positions=0,
                max_positions=5,
                consecutive_stops=0,
                kill_switch_active=True,
                kill_switch_reason="test kill switch",
            )
        )
        await session.commit()

    rest = _upbit_rest_client_with(_upbit_handler())
    async with session_scope() as session:
        data = await gather_upbit_revalidation_input(session, rest, approval, rec)

    assert data.risk_state is not None
    assert data.risk_state.kill_switch_active is True
    assert data.risk_state.kill_switch_reason == "test kill switch"
