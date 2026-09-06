"""P15 acceptance: Upbit order execution - the LIVE_TRADING safety gate,
no blind retries, and best-effort reconciliation (honestly heuristic, since
Upbit has no verified client-side idempotency key - see execution.py's
module docstring).

Real local Postgres for the `Order` ledger; the Upbit transport is mocked
(httpx.MockTransport) - never a real Upbit connection, and this file never
places a live order regardless of LIVE_TRADING, since LIVE_TRADING here
only unlocks calls into the *mocked* transport.
"""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import delete, select

from app.core.config import Settings
from app.db.models import Order
from app.db.session import session_scope
from app.execution.errors import LiveTradingDisabledError, OrderTimeoutError
from app.integrations.upbit.auth import UpbitAuth
from app.integrations.upbit.errors import UpbitApiError
from app.integrations.upbit.execution import UpbitExecutionProvider
from app.integrations.upbit.orders import UpbitOrderClient

pytestmark = [pytest.mark.P15, pytest.mark.asyncio]

_TEST_SYMBOL = "KRW-UPBITEXEC-TEST"


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"live_trading": True}
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _provider_with(handler, settings: Settings | None = None) -> UpbitExecutionProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.upbit.test")
    order_client = UpbitOrderClient(client, UpbitAuth("access-1", "secret-1"))
    return UpbitExecutionProvider(order_client, settings=settings or _settings())


@pytest.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(Order).where(Order.symbol == _TEST_SYMBOL))
        await session.commit()


async def _order_count() -> int:
    async with session_scope() as session:
        result = await session.execute(select(Order).where(Order.symbol == _TEST_SYMBOL))
        return len(result.scalars().all())


# --- absolute safety rule ------------------------------------------------


async def test_place_order_refuses_when_live_trading_disabled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not make any network call when LIVE_TRADING is disabled")

    provider = _provider_with(handler, settings=_settings(live_trading=False))

    async with session_scope() as session:
        with pytest.raises(LiveTradingDisabledError):
            await provider.place_order(
                session,
                trade_plan_id=None,
                symbol=_TEST_SYMBOL,
                side="BUY",
                ord_type="limit",
                volume="1",
                price="1000",
            )

    assert await _order_count() == 0


async def test_cancel_order_refuses_when_live_trading_disabled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not make any network call when LIVE_TRADING is disabled")

    provider = _provider_with(handler, settings=_settings(live_trading=False))
    order = Order(
        id="fake-upbit-order-1",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="limit",
        quantity=1,
        price=1000,
        status="SUBMITTED",
        broker="UPBIT",
        broker_order_id="broker-uuid-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        with pytest.raises(LiveTradingDisabledError):
            await provider.cancel_order(session, order=order)


# --- place_order --------------------------------------------------------


async def test_place_order_success_marks_submitted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"uuid": "broker-uuid-abc", "state": "wait"})

    provider = _provider_with(handler)

    async with session_scope() as session:
        order = await provider.place_order(
            session,
            trade_plan_id=None,
            symbol=_TEST_SYMBOL,
            side="BUY",
            ord_type="limit",
            volume="1",
            price="1000",
        )

    assert order.status == "SUBMITTED"
    assert order.broker_order_id == "broker-uuid-abc"


async def test_place_order_rejects_invalid_side() -> None:
    provider = _provider_with(lambda r: httpx.Response(200))
    async with session_scope() as session:
        with pytest.raises(ValueError, match="BUY or SELL"):
            await provider.place_order(
                session, trade_plan_id=None, symbol=_TEST_SYMBOL, side="HOLD", ord_type="limit"
            )


async def test_place_order_timeout_marks_unknown_and_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)

    provider = _provider_with(handler)

    async with session_scope() as session:
        with pytest.raises(OrderTimeoutError) as exc_info:
            await provider.place_order(
                session,
                trade_plan_id=None,
                symbol=_TEST_SYMBOL,
                side="BUY",
                ord_type="limit",
                volume="1",
                price="1000",
            )

    async with session_scope() as session:
        result = await session.execute(select(Order).where(Order.id == exc_info.value.client_order_id))
        order = result.scalar_one()
    assert order.status == "UNKNOWN"
    assert order.broker_order_id is None


async def test_place_order_api_error_marks_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"name": "invalid_query", "message": "bad"}})

    provider = _provider_with(handler)

    async with session_scope() as session:
        with pytest.raises(UpbitApiError):
            await provider.place_order(
                session,
                trade_plan_id=None,
                symbol=_TEST_SYMBOL,
                side="BUY",
                ord_type="limit",
                volume="1",
                price="1000",
            )

    async with session_scope() as session:
        result = await session.execute(select(Order).where(Order.symbol == _TEST_SYMBOL))
        order = result.scalar_one()
    assert order.status == "REJECTED"


# --- cancel ----------------------------------------------------------------


async def test_cancel_order_success_marks_cancelled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"uuid": "broker-uuid-1", "state": "cancel"})

    provider = _provider_with(handler)
    order = Order(
        id="fake-upbit-order-cancel",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="limit",
        quantity=1,
        price=1000,
        status="SUBMITTED",
        broker="UPBIT",
        broker_order_id="broker-uuid-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        session.add(order)
        await session.commit()
        result = await provider.cancel_order(session, order=order)

    assert result.status == "CANCELLED"


async def test_cancel_order_raises_without_broker_order_id() -> None:
    provider = _provider_with(lambda r: httpx.Response(200))
    order = Order(
        id="fake-upbit-order-no-id",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="limit",
        quantity=1,
        price=1000,
        status="UNKNOWN",
        broker="UPBIT",
        broker_order_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        with pytest.raises(ValueError, match="reconcile first"):
            await provider.cancel_order(session, order=order)


# --- reconciliation ----------------------------------------------------


async def test_reconcile_order_finds_match_and_updates_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        state = request.url.params.get("state")
        if state == "wait":
            return httpx.Response(
                200,
                json=[{"uuid": "broker-found", "side": "bid", "volume": "1", "state": "wait"}],
            )
        return httpx.Response(200, json=[])

    provider = _provider_with(handler)
    order = Order(
        id="fake-upbit-order-reconcile",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="limit",
        quantity=1,
        price=1000,
        status="UNKNOWN",
        broker="UPBIT",
        broker_order_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        session.add(order)
        await session.commit()
        result = await provider.reconcile_order(session, order=order)

    assert result.broker_order_id == "broker-found"
    assert result.status == "SUBMITTED"


async def test_reconcile_order_leaves_unknown_when_no_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    provider = _provider_with(handler)
    order = Order(
        id="fake-upbit-order-no-match",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="limit",
        quantity=1,
        price=1000,
        status="UNKNOWN",
        broker="UPBIT",
        broker_order_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        session.add(order)
        await session.commit()
        result = await provider.reconcile_order(session, order=order)

    assert result.status == "UNKNOWN"
    assert result.broker_order_id is None


async def test_reconcile_order_skips_network_call_for_settled_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not query the broker for an already-settled order")

    provider = _provider_with(handler)
    order = Order(
        id="fake-upbit-order-settled",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="limit",
        quantity=1,
        price=1000,
        status="FILLED",
        broker="UPBIT",
        broker_order_id="broker-settled",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        session.add(order)
        await session.commit()
        result = await provider.reconcile_order(session, order=order)

    assert result.status == "FILLED"
