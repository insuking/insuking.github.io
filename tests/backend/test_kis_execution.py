"""P29 acceptance: KIS order execution - the LIVE_TRADING safety gate, no
blind retries, and the explicit "reconciliation not supported" refusal
(see execution.py's module docstring for why, unlike Toss/Upbit).

Real local Postgres for the `Order` ledger (same pattern as
test_upbit_execution.py); the KIS transport is mocked (httpx.MockTransport)
- never a real KIS connection, and this file never places a live order
regardless of LIVE_TRADING, since LIVE_TRADING here only unlocks calls
into the *mocked* transport.
"""

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import delete, select

from app.core.config import Settings
from app.db.models import Order
from app.db.session import session_scope
from app.execution.errors import LiveTradingDisabledError, OrderTimeoutError
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.execution import KisExecutionProvider, KisReconciliationNotSupportedError
from app.integrations.kis.orders import KisOrderClient

pytestmark = [pytest.mark.P29, pytest.mark.asyncio]

_TEST_SYMBOL = "KISEXEC-TEST"


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"live_trading": True, "kis_app_key": "k", "kis_app_secret": "s"}
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _provider_with(
    handler: Callable[[httpx.Request], httpx.Response], settings: Settings | None = None
) -> KisExecutionProvider:
    resolved_settings = settings or _settings()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    auth = KisAuth(client=client, settings=resolved_settings)
    order_client = KisOrderClient(client, auth, "12345678", "01", paper_trading=True)
    return KisExecutionProvider(order_client, settings=resolved_settings)


@pytest.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(Order).where(Order.symbol == _TEST_SYMBOL))
        await session.commit()


def _token_handler(inner: Callable[[httpx.Request], httpx.Response]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        return inner(request)

    return handler


# --- absolute safety rule -------------------------------------------------


async def test_place_order_refuses_when_live_trading_disabled() -> None:
    provider = _provider_with(lambda r: httpx.Response(500), settings=_settings(live_trading=False))

    async with session_scope() as session:
        with pytest.raises(LiveTradingDisabledError):
            await provider.place_order(
                session, trade_plan_id=None, symbol=_TEST_SYMBOL, side="BUY", quantity="1", price="70000"
            )


async def test_cancel_order_refuses_when_live_trading_disabled() -> None:
    provider = _provider_with(lambda r: httpx.Response(500), settings=_settings(live_trading=False))
    order = Order(
        id="kis-order-1",
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="LIMIT",
        quantity=1.0,
        price=70000.0,
        status="SUBMITTED",
        broker="KIS",
        broker_order_id="0000117057",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        with pytest.raises(LiveTradingDisabledError):
            await provider.cancel_order(session, order=order, krx_fwdg_ord_orgno="06010")


# --- place_order -----------------------------------------------------------


async def test_place_order_success_marks_submitted_with_broker_order_id() -> None:
    def inner(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"rt_cd": "0", "output": {"KRX_FWDG_ORD_ORGNO": "06010", "ODNO": "0000117057"}}
        )

    provider = _provider_with(_token_handler(inner))

    async with session_scope() as session:
        order = await provider.place_order(
            session, trade_plan_id=None, symbol=_TEST_SYMBOL, side="BUY", quantity="1", price="70000"
        )

    assert order.status == "SUBMITTED"
    assert order.broker_order_id == "0000117057"
    assert order.broker == "KIS"


async def test_place_order_rejects_invalid_side() -> None:
    provider = _provider_with(_token_handler(lambda r: httpx.Response(200, json={"rt_cd": "0", "output": {}})))

    async with session_scope() as session:
        with pytest.raises(ValueError):
            await provider.place_order(
                session, trade_plan_id=None, symbol=_TEST_SYMBOL, side="HOLD", quantity="1", price="70000"
            )


async def test_place_order_timeout_marks_unknown_and_raises() -> None:
    def inner(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    provider = _provider_with(_token_handler(inner))

    async with session_scope() as session:
        with pytest.raises(OrderTimeoutError):
            await provider.place_order(
                session, trade_plan_id=None, symbol=_TEST_SYMBOL, side="BUY", quantity="1", price="70000"
            )
        result = await session.execute(select(Order).where(Order.symbol == _TEST_SYMBOL))
        order = result.scalars().one()
        assert order.status == "UNKNOWN"


async def test_place_order_api_error_marks_rejected() -> None:
    def inner(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rt_cd": "1", "msg1": "주문가능금액을 초과하였습니다."})

    provider = _provider_with(_token_handler(inner))

    async with session_scope() as session:
        with pytest.raises(KisApiError):
            await provider.place_order(
                session, trade_plan_id=None, symbol=_TEST_SYMBOL, side="BUY", quantity="1", price="70000"
            )
        result = await session.execute(select(Order).where(Order.symbol == _TEST_SYMBOL))
        order = result.scalars().one()
        assert order.status == "REJECTED"


# --- cancel_order ------------------------------------------------------------


async def test_cancel_order_success_marks_cancelled() -> None:
    def inner(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rt_cd": "0", "output": {"ODNO": "0000117058"}})

    provider = _provider_with(_token_handler(inner))
    order = Order(
        id="kis-order-2",
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="LIMIT",
        quantity=1.0,
        price=70000.0,
        status="SUBMITTED",
        broker="KIS",
        broker_order_id="0000117057",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        session.add(order)
        await session.commit()
        result = await provider.cancel_order(session, order=order, krx_fwdg_ord_orgno="06010")

    assert result.status == "CANCELLED"


async def test_cancel_order_raises_without_broker_order_id() -> None:
    provider = _provider_with(_token_handler(lambda r: httpx.Response(200, json={"rt_cd": "0", "output": {}})))
    order = Order(
        id="kis-order-3",
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="LIMIT",
        quantity=1.0,
        price=70000.0,
        status="PENDING",
        broker="KIS",
        broker_order_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        with pytest.raises(ValueError):
            await provider.cancel_order(session, order=order, krx_fwdg_ord_orgno="06010")


# --- reconcile_order: explicitly not supported ------------------------------


async def test_reconcile_order_always_raises_not_supported() -> None:
    provider = _provider_with(_token_handler(lambda r: httpx.Response(200, json={"rt_cd": "0", "output": {}})))
    order = Order(
        id="kis-order-4",
        symbol=_TEST_SYMBOL,
        side="BUY",
        order_type="LIMIT",
        quantity=1.0,
        price=70000.0,
        status="UNKNOWN",
        broker="KIS",
        broker_order_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        with pytest.raises(KisReconciliationNotSupportedError):
            await provider.reconcile_order(session, order=order)
