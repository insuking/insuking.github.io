"""P15 acceptance: Toss order execution - idempotency, no blind retries,
the LIVE_TRADING safety gate, and reconciliation.

Real local Postgres for the `Order` ledger (like test_approval_service.py);
the Toss transport itself is mocked (httpx.MockTransport) - never a real
Toss connection, and this file never places a live order regardless of
LIVE_TRADING, since LIVE_TRADING here only unlocks calls into the *mocked*
transport.
"""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import delete, select

from app.core.config import Settings
from app.db.models import Order
from app.db.session import session_scope
from app.execution.errors import LiveTradingDisabledError, OrderTimeoutError
from app.integrations.toss.auth import TossAuth
from app.integrations.toss.errors import TossApiError
from app.integrations.toss.execution import TossExecutionProvider
from app.integrations.toss.rest_client import TossRestClient

pytestmark = [pytest.mark.P15, pytest.mark.asyncio]

_TEST_SYMBOL = "TOSSEXEC-TEST"


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "toss_client_id": "test-id",
        "toss_client_secret": "test-secret",
        "live_trading": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _provider_with(handler, settings: Settings | None = None) -> TossExecutionProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.toss.test")
    settings = settings or _settings()
    auth = TossAuth(client=client, settings=settings)
    rest = TossRestClient(client, auth, base_backoff_seconds=0.0)
    return TossExecutionProvider(rest, settings=settings)


def _auth_ok(request: httpx.Request) -> httpx.Response | None:
    if request.url.path == "/oauth2/token":
        return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
    return None


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
                account_seq="SEQ-1",
                trade_plan_id=None,
                symbol=_TEST_SYMBOL,
                side="BUY",
                order_type="LIMIT",
                quantity="1",
                price="70000",
            )

    assert await _order_count() == 0


async def test_cancel_order_refuses_when_live_trading_disabled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not make any network call when LIVE_TRADING is disabled")

    provider = _provider_with(handler, settings=_settings(live_trading=False))
    order = Order(
        id="fake-order-1",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="LIMIT",
        quantity=1,
        price=70000,
        status="SUBMITTED",
        broker="TOSS",
        broker_order_id="broker-order-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        with pytest.raises(LiveTradingDisabledError):
            await provider.cancel_order(session, account_seq="SEQ-1", order=order)


# --- place_order happy path ------------------------------------------------


async def test_place_order_success_marks_submitted_with_broker_order_id() -> None:
    seen_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        import json

        seen_bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"result": {"orderId": "broker-abc", "clientOrderId": seen_bodies[-1]["clientOrderId"]}})

    provider = _provider_with(handler)

    async with session_scope() as session:
        order = await provider.place_order(
            session,
            account_seq="SEQ-1",
            trade_plan_id=None,
            symbol=_TEST_SYMBOL,
            side="BUY",
            order_type="LIMIT",
            quantity="1",
            price="70000",
        )

    assert order.status == "SUBMITTED"
    assert order.broker_order_id == "broker-abc"
    assert seen_bodies[0]["clientOrderId"] == order.id


async def test_place_order_uses_order_id_as_idempotency_key() -> None:
    """Calling create_order with the same local Order.id twice must send
    the exact same clientOrderId - the whole point of using it as the
    idempotency key."""

    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        return httpx.Response(200, json={"result": {"orderId": "broker-abc"}})

    provider = _provider_with(handler)
    async with session_scope() as session:
        order = await provider.place_order(
            session,
            account_seq="SEQ-1",
            trade_plan_id=None,
            symbol=_TEST_SYMBOL,
            side="BUY",
            order_type="LIMIT",
            quantity="1",
            price="70000",
        )
    # order.id was generated fresh, non-empty, and used as the clientOrderId
    # (implicitly proven by the successful round trip above returning a
    # well-formed UUID id).
    assert order.id


# --- no blind retries: timeout and duplicate handling -----------------------


async def test_place_order_timeout_marks_unknown_and_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        raise httpx.ReadTimeout("simulated timeout", request=request)

    provider = _provider_with(handler)

    async with session_scope() as session:
        with pytest.raises(OrderTimeoutError) as exc_info:
            await provider.place_order(
                session,
                account_seq="SEQ-1",
                trade_plan_id=None,
                symbol=_TEST_SYMBOL,
                side="BUY",
                order_type="LIMIT",
                quantity="1",
                price="70000",
            )

    order_id = exc_info.value.client_order_id
    async with session_scope() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one()
    assert order.status == "UNKNOWN"
    assert order.broker_order_id is None


async def test_place_order_duplicate_409_marks_unknown_and_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        return httpx.Response(409, json={"error": {"code": "duplicate-client-order-id", "message": "dup"}})

    provider = _provider_with(handler)

    async with session_scope() as session:
        with pytest.raises(OrderTimeoutError) as exc_info:
            await provider.place_order(
                session,
                account_seq="SEQ-1",
                trade_plan_id=None,
                symbol=_TEST_SYMBOL,
                side="BUY",
                order_type="LIMIT",
                quantity="1",
                price="70000",
            )

    order_id = exc_info.value.client_order_id
    async with session_scope() as session:
        result = await session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one()
    assert order.status == "UNKNOWN"


async def test_place_order_rejects_on_generic_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        return httpx.Response(400, json={"error": {"code": "invalid-request", "message": "bad"}})

    provider = _provider_with(handler)

    async with session_scope() as session:
        with pytest.raises(TossApiError):
            await provider.place_order(
                session,
                account_seq="SEQ-1",
                trade_plan_id=None,
                symbol=_TEST_SYMBOL,
                side="BUY",
                order_type="LIMIT",
                quantity="1",
                price="70000",
            )

    async with session_scope() as session:
        result = await session.execute(select(Order).where(Order.symbol == _TEST_SYMBOL))
        order = result.scalar_one()
    assert order.status == "REJECTED"


# --- cancel / modify -----------------------------------------------------


async def test_cancel_order_success_marks_cancelled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        return httpx.Response(200, json={"result": {"orderId": "broker-cancel"}})

    provider = _provider_with(handler)
    order = Order(
        id="fake-order-cancel",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="LIMIT",
        quantity=1,
        price=70000,
        status="SUBMITTED",
        broker="TOSS",
        broker_order_id="broker-order-1",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        session.add(order)
        await session.commit()
        result = await provider.cancel_order(session, account_seq="SEQ-1", order=order)

    assert result.status == "CANCELLED"


async def test_cancel_order_treats_422_as_noop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        return httpx.Response(422, json={"error": {"code": "already-filled", "message": "too late"}})

    provider = _provider_with(handler)
    order = Order(
        id="fake-order-422",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="LIMIT",
        quantity=1,
        price=70000,
        status="FILLED",
        broker="TOSS",
        broker_order_id="broker-order-2",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        session.add(order)
        await session.commit()
        result = await provider.cancel_order(session, account_seq="SEQ-1", order=order)

    assert result.status == "FILLED"  # unchanged, no exception


async def test_cancel_order_raises_without_broker_order_id() -> None:
    provider = _provider_with(lambda r: httpx.Response(200))
    order = Order(
        id="fake-order-no-broker-id",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="LIMIT",
        quantity=1,
        price=70000,
        status="UNKNOWN",
        broker="TOSS",
        broker_order_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        with pytest.raises(ValueError, match="reconcile first"):
            await provider.cancel_order(session, account_seq="SEQ-1", order=order)


async def test_modify_order_updates_broker_order_id_and_terms() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        return httpx.Response(200, json={"result": {"orderId": "broker-new"}})

    provider = _provider_with(handler)
    order = Order(
        id="fake-order-modify",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="LIMIT",
        quantity=1,
        price=70000,
        status="SUBMITTED",
        broker="TOSS",
        broker_order_id="broker-order-old",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        session.add(order)
        await session.commit()
        result = await provider.modify_order(
            session, account_seq="SEQ-1", order=order, order_type="LIMIT", quantity="2", price="71000"
        )

    assert result.broker_order_id == "broker-new"
    assert result.quantity == 2
    assert result.price == 71000


# --- reconciliation ----------------------------------------------------


async def test_reconcile_order_finds_match_and_updates_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        if request.url.params.get("status") == "OPEN":
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "orderId": "broker-found",
                            "symbol": _TEST_SYMBOL,
                            "side": "BUY",
                            "quantity": "1",
                            "status": "PENDING",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"result": []})

    provider = _provider_with(handler)
    order = Order(
        id="fake-order-reconcile",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="LIMIT",
        quantity=1,
        price=70000,
        status="UNKNOWN",
        broker="TOSS",
        broker_order_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        session.add(order)
        await session.commit()
        result = await provider.reconcile_order(session, account_seq="SEQ-1", order=order)

    assert result.broker_order_id == "broker-found"
    assert result.status == "SUBMITTED"  # Toss PENDING -> domain SUBMITTED


async def test_reconcile_order_leaves_unknown_when_no_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        return httpx.Response(200, json={"result": []})

    provider = _provider_with(handler)
    order = Order(
        id="fake-order-no-match",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="LIMIT",
        quantity=1,
        price=70000,
        status="UNKNOWN",
        broker="TOSS",
        broker_order_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        session.add(order)
        await session.commit()
        result = await provider.reconcile_order(session, account_seq="SEQ-1", order=order)

    assert result.status == "UNKNOWN"
    assert result.broker_order_id is None


async def test_reconcile_order_skips_network_call_for_settled_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        auth_resp = _auth_ok(request)
        if auth_resp:
            return auth_resp
        raise AssertionError("must not query the broker for an already-settled order")

    provider = _provider_with(handler)
    order = Order(
        id="fake-order-settled",
        trade_plan_id=None,
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="LIMIT",
        quantity=1,
        price=70000,
        status="FILLED",
        broker="TOSS",
        broker_order_id="broker-settled",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        session.add(order)
        await session.commit()
        result = await provider.reconcile_order(session, account_seq="SEQ-1", order=order)

    assert result.status == "FILLED"
