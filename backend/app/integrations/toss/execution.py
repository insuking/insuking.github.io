"""Toss order execution (P15).

The order-placement half of the Toss integration - place/modify/cancel real
orders, idempotently, with no blind retries. See
app/integrations/toss/rest_client.py's module docstring for exactly what
was verified about the underlying API, and docs/TOSS_SETUP.md for the full
notes.

Idempotency: this project's own `Order.id` (a UUID generated *before* the
broker is ever called) doubles as the `clientOrderId` sent to Toss. Toss's
OpenAPI schema documents `POST /api/v1/orders` returning `409` for a reused
`clientOrderId` - so resubmitting the same local `Order.id` after an
uncertain outcome is safe at the broker rather than something this module
has to prevent by itself. What the schema does **not** expose:
`clientOrderId` on orders returned by `get_order`/`get_orders` - so
`reconcile_order()` can't look an order up by idempotency key after the
fact. It falls back to matching by symbol/side/quantity/price among recent
orders, which is a heuristic, not a guarantee - see its docstring.

No blind retries: `place_order()` never resubmits automatically on a
timeout or a 409 - it marks the local order `UNKNOWN` and raises
`OrderTimeoutError`. Callers (a human operator today; a future P19 watchdog
job) must call `reconcile_order()` before doing anything else with that
order.

Absolute safety rule: every mutating method refuses to run at all unless
`settings.live_trading` is `True` - see `LiveTradingDisabledError`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import Order
from app.execution.errors import LiveTradingDisabledError, OrderTimeoutError
from app.integrations.toss.errors import TossApiError, TossDuplicateOrderError
from app.integrations.toss.rest_client import TossRestClient

_QUANTITY_MATCH_TOLERANCE = 1e-9

_TOSS_STATUS_TO_DOMAIN = {
    "PENDING": "SUBMITTED",
    "PENDING_CANCEL": "SUBMITTED",
    "PENDING_REPLACE": "SUBMITTED",
    "PARTIAL_FILLED": "PARTIALLY_FILLED",
    "FILLED": "FILLED",
    "CANCELED": "CANCELLED",
    "REJECTED": "REJECTED",
    # A cancel/modify Toss itself rejected reverts the original order to
    # whatever it was before - so the safest domain mapping is "still live".
    "CANCEL_REJECTED": "SUBMITTED",
    "REPLACE_REJECTED": "SUBMITTED",
    "REPLACED": "SUBMITTED",
}


def _map_toss_status(status: object) -> str:
    if isinstance(status, str) and status in _TOSS_STATUS_TO_DOMAIN:
        return _TOSS_STATUS_TO_DOMAIN[status]
    return "UNKNOWN"


class TossExecutionProvider:
    def __init__(
        self, rest_client: TossRestClient, settings: Settings | None = None
    ) -> None:
        self._rest = rest_client
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
        account_seq: str,
        trade_plan_id: str | None,
        symbol: str,
        side: str,
        order_type: str,
        quantity: str,
        price: str | None = None,
    ) -> Order:
        """Places a real order. Raises `LiveTradingDisabledError` immediately
        if `LIVE_TRADING` isn't enabled - no network call happens first."""
        self._require_live_trading()

        now = datetime.now(UTC)
        order = Order(
            id=str(uuid.uuid4()),
            trade_plan_id=trade_plan_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=float(quantity),
            price=float(price) if price is not None else None,
            status="PENDING",
            broker="TOSS",
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        await session.commit()

        try:
            result = await self._rest.create_order(
                account_seq,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                client_order_id=order.id,
            )
        except httpx.TimeoutException as exc:
            await self._mark(session, order, "UNKNOWN")
            raise OrderTimeoutError(
                f"Toss create_order timed out for order {order.id} - reconcile before retrying",
                client_order_id=order.id,
            ) from exc
        except TossDuplicateOrderError as exc:
            # Toss's own idempotency signal: this clientOrderId was already
            # submitted. The original call may have succeeded - don't
            # guess, make the caller reconcile explicitly.
            await self._mark(session, order, "UNKNOWN")
            raise OrderTimeoutError(
                f"Toss reported clientOrderId {order.id} as a duplicate - reconcile before retrying",
                client_order_id=order.id,
            ) from exc
        except TossApiError:
            await self._mark(session, order, "REJECTED")
            raise

        order.broker_order_id = result.get("orderId") if isinstance(result, dict) else None
        await self._mark(session, order, "SUBMITTED")
        return order

    async def cancel_order(self, session: AsyncSession, *, account_seq: str, order: Order) -> Order:
        self._require_live_trading()
        if order.broker_order_id is None:
            raise ValueError("Cannot cancel an order with no broker_order_id - reconcile first")

        try:
            await self._rest.cancel_order(account_seq, order.broker_order_id)
        except TossApiError as exc:
            if exc.status_code == 422:
                # Business-rule violation - almost always "already
                # filled/cancelled". The caller's intent (this order should
                # not remain open) is already satisfied; treat as a no-op
                # rather than raising.
                return order
            raise

        await self._mark(session, order, "CANCELLED")
        return order

    async def modify_order(
        self,
        session: AsyncSession,
        *,
        account_seq: str,
        order: Order,
        order_type: str,
        quantity: str,
        price: str | None = None,
    ) -> Order:
        self._require_live_trading()
        if order.broker_order_id is None:
            raise ValueError("Cannot modify an order with no broker_order_id - reconcile first")

        result = await self._rest.modify_order(
            account_seq, order.broker_order_id, order_type=order_type, quantity=quantity, price=price
        )
        # A successful modify issues a *new* orderId (the original is
        # superseded, not mutated in place) - see docs/TOSS_SETUP.md.
        if isinstance(result, dict) and result.get("orderId"):
            order.broker_order_id = result["orderId"]
        order.order_type = order_type
        order.quantity = float(quantity)
        order.price = float(price) if price is not None else None
        order.updated_at = datetime.now(UTC)
        await session.commit()
        return order

    async def reconcile_order(self, session: AsyncSession, *, account_seq: str, order: Order) -> Order:
        """Best-effort recovery for an order left in `PENDING`/`UNKNOWN` by a
        timeout or a `409`. Toss doesn't expose `clientOrderId` on listed
        orders (see module docstring), so this matches by
        symbol/side/quantity/price among recent orders - a heuristic, not a
        guarantee. Never places a new order; only updates this row's status
        from what the broker actually reports, or leaves it `UNKNOWN` if no
        confident match is found (per docs/MASTER_SPEC.md's Final
        Instruction: uncertain order state must block new trades, not be
        guessed away).
        """
        if order.status not in ("PENDING", "UNKNOWN"):
            return order

        open_orders = await self._rest.get_orders(account_seq, status="OPEN")
        closed_orders = await self._rest.get_orders(account_seq, status="CLOSED")
        candidates = [
            *(open_orders if isinstance(open_orders, list) else []),
            *(closed_orders if isinstance(closed_orders, list) else []),
        ]

        match = self._find_match(order, candidates)
        if match is not None:
            order.broker_order_id = match.get("orderId")
            await self._mark(session, order, _map_toss_status(match.get("status")))
        return order

    @staticmethod
    def _find_match(order: Order, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        for candidate in candidates:
            if (
                candidate.get("symbol") == order.symbol
                and candidate.get("side") == order.side
                and _quantity_matches(candidate.get("quantity"), order.quantity)
            ):
                return candidate
        return None

    @staticmethod
    async def _mark(session: AsyncSession, order: Order, status: str) -> None:
        order.status = status
        order.updated_at = datetime.now(UTC)
        await session.commit()


def _quantity_matches(broker_quantity: object, local_quantity: float) -> bool:
    if not isinstance(broker_quantity, str):
        return False
    try:
        return abs(float(broker_quantity) - local_quantity) < _QUANTITY_MATCH_TOLERANCE
    except ValueError:
        return False
