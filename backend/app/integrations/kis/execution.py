"""KIS order execution (P29): place/cancel a real domestic-stock order,
with no blind retries. See `orders.py`'s module docstring for exactly
what was verified about `order-cash`/`order-rvsecncl`.

Idempotency: like Upbit (see `app/integrations/upbit/execution.py`) and
unlike Toss, KIS's `order-cash` body has no client-supplied idempotency
field this project could confirm (see `orders.py`'s docstring - CANO/
ACNT_PRDT_CD/PDNO/ORD_DVSN/ORD_QTY/ORD_UNPR/EXCG_ID_DVSN_CD is the full
verified field list). A timeout can't be resubmitted blindly, so
`place_order()` marks the local order `UNKNOWN` and raises
`OrderTimeoutError`, same as every other provider in this project.

**`reconcile_order()` is not implemented.** Toss/Upbit's versions do
best-effort symbol/side/quantity matching against a real order-listing
endpoint this project had already verified in an earlier phase (P5/P7).
KIS has no equivalent here yet: `inquire-daily-ccld` (일별주문체결조회,
the natural candidate) needs mandatory pagination tokens and an account-
type filter (`INQR_DVSN_3`) this project has not confirmed real values
for, and its per-row response field names (fill quantity, fill price,
status) were never independently confirmed either - unlike everywhere
else in this project, guessing at *both* the request shape and the
response shape at once for the one endpoint whose whole job is "tell me
what actually happened to a real order" is a worse trade than admitting
the gap. An `UNKNOWN` order from a KIS timeout must be checked by hand in
the KIS HTS/app - `KisReconciliationNotSupportedError` says so instead of
silently returning a guessed answer.

Absolute safety rule (same as Toss/Upbit): every mutating method refuses
to run at all unless `settings.live_trading` is `True`. `place_order()`
additionally exists inside `KisOrderClient`'s own `paper_trading` switch
(default `True` - see `Settings.kis_paper_trading`), so getting real
money routing requires two explicit, independent settings to both be
deliberately changed from their safe defaults, not one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Order
from app.execution.errors import ExecutionError, LiveTradingDisabledError, OrderTimeoutError
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.orders import ORDER_DIVISION_LIMIT, KisOrderClient

_SIDES = ("BUY", "SELL")


class KisReconciliationNotSupportedError(ExecutionError):
    """Raised by `reconcile_order()` - see this module's docstring for why
    KIS reconciliation isn't implemented yet. Check the KIS HTS/app
    directly for this order's real status."""


class KisExecutionProvider:
    def __init__(self, order_client: KisOrderClient, settings: Settings | None = None) -> None:
        self._orders = order_client
        self.settings = settings or get_settings()

    def _require_live_trading(self) -> None:
        if not self.settings.live_trading:
            raise LiveTradingDisabledError(
                "LIVE_TRADING is not enabled - see docs/MASTER_SPEC.md section A"
            )

    async def place_order(
        self,
        session: AsyncSession,
        *,
        trade_plan_id: str | None,
        symbol: str,
        side: str,
        quantity: str,
        price: str | None = None,
        order_division: str = ORDER_DIVISION_LIMIT,
    ) -> Order:
        """Places a real order. Raises `LiveTradingDisabledError`
        immediately if `LIVE_TRADING` isn't enabled - no network call
        happens first."""
        self._require_live_trading()
        if side not in _SIDES:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")

        now = datetime.now(UTC)
        order = Order(
            id=str(uuid.uuid4()),
            trade_plan_id=trade_plan_id,
            symbol=symbol,
            side=side,
            order_type="LIMIT" if order_division == ORDER_DIVISION_LIMIT else "MARKET",
            quantity=float(quantity),
            price=float(price) if price is not None else None,
            status="PENDING",
            broker="KIS",
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        await session.commit()

        try:
            result = await self._orders.place_order(
                symbol=symbol, side=side, quantity=quantity, price=price, order_division=order_division
            )
        except httpx.TimeoutException as exc:
            await self._mark(session, order, "UNKNOWN")
            raise OrderTimeoutError(
                f"KIS place_order timed out for order {order.id} - check the KIS HTS/app before "
                "retrying (reconcile_order() is not supported for KIS yet, see module docstring)",
                client_order_id=order.id,
            ) from exc
        except KisApiError:
            await self._mark(session, order, "REJECTED")
            raise

        output = result.get("output") if isinstance(result, dict) else None
        if isinstance(output, dict):
            order.broker_order_id = output.get("ODNO")
        await self._mark(session, order, "SUBMITTED")
        return order

    async def cancel_order(
        self, session: AsyncSession, *, order: Order, krx_fwdg_ord_orgno: str
    ) -> Order:
        """`krx_fwdg_ord_orgno` must come from that order's own
        `place_order()` response (see `orders.py`'s `cancel_order()`
        docstring) - this project has no place to store it on the `Order`
        row yet, so callers must keep it themselves (e.g. from the
        `place_order()` result) until a schema change adds one."""
        self._require_live_trading()
        if order.broker_order_id is None:
            raise ValueError("Cannot cancel an order with no broker_order_id")

        await self._orders.cancel_order(
            krx_fwdg_ord_orgno=krx_fwdg_ord_orgno,
            original_order_no=order.broker_order_id,
            symbol=order.symbol,
        )
        await self._mark(session, order, "CANCELLED")
        return order

    async def reconcile_order(self, session: AsyncSession, *, order: Order) -> Order:
        raise KisReconciliationNotSupportedError(
            f"Cannot reconcile KIS order {order.id} automatically - check the KIS HTS/app for its "
            "real status, then update this row by hand. See KisExecutionProvider's module docstring."
        )

    @staticmethod
    async def _mark(session: AsyncSession, order: Order, status: str) -> None:
        order.status = status
        order.updated_at = datetime.now(UTC)
        await session.commit()
