"""Upbit order execution (P15): place/cancel/status, idempotent as far as
this codebase can make it, with no blind retries.

Idempotency - the important difference from Toss (see
app/integrations/toss/execution.py): pyupbit, this project's only reachable
verification source for Upbit's authenticated API, does not implement or
document a client-supplied idempotency key (its own source has TODO
comments acknowledging "identifiers" support is missing - see
app/integrations/upbit/orders.py's module docstring). This implementation
does **not** invent one. Practical consequence: if `place_order()` times
out, this codebase cannot prove one way or the other whether the order was
actually placed - reconciliation can only search recent orders by
side/volume/price and hope for an unambiguous match. This is the single
best reason docs/MASTER_SPEC.md's "no blind retries" rule exists: retrying
blindly here could place a genuine duplicate order with real money, so a
timeout always ends in `UNKNOWN` + `OrderTimeoutError`, never an automatic
resubmission - a human (or a future P19 watchdog) must resolve it.

Absolute safety rule: every mutating method refuses to run at all unless
`settings.live_trading` is `True`.
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
from app.integrations.upbit.errors import UpbitApiError
from app.integrations.upbit.orders import UpbitOrderClient

_SIDE_TO_UPBIT = {"BUY": "bid", "SELL": "ask"}
_QUANTITY_MATCH_TOLERANCE = 1e-9

# Upbit order `state` values, per pyupbit: wait/watch (open), done (filled),
# cancel (cancelled). There is no "rejected" state exposed the same way
# Toss has one - an order either gets accepted (wait) or the placement call
# itself errors.
_UPBIT_STATE_TO_DOMAIN = {
    "wait": "SUBMITTED",
    "watch": "SUBMITTED",
    "done": "FILLED",
    "cancel": "CANCELLED",
}


def _map_upbit_state(state: object) -> str:
    if isinstance(state, str) and state in _UPBIT_STATE_TO_DOMAIN:
        return _UPBIT_STATE_TO_DOMAIN[state]
    return "UNKNOWN"


class UpbitExecutionProvider:
    def __init__(self, order_client: UpbitOrderClient, settings: Settings | None = None) -> None:
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
        ord_type: str,
        volume: str | None = None,
        price: str | None = None,
    ) -> Order:
        self._require_live_trading()
        if side not in _SIDE_TO_UPBIT:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")

        now = datetime.now(UTC)
        order = Order(
            id=str(uuid.uuid4()),
            trade_plan_id=trade_plan_id,
            symbol=symbol,
            side=side,
            order_type=ord_type,
            quantity=float(volume) if volume is not None else 0.0,
            price=float(price) if price is not None else None,
            status="PENDING",
            broker="UPBIT",
            created_at=now,
            updated_at=now,
        )
        session.add(order)
        await session.commit()

        try:
            result = await self._orders.place_order(
                market=symbol,
                side=_SIDE_TO_UPBIT[side],
                ord_type=ord_type,
                volume=volume,
                price=price,
            )
        except httpx.TimeoutException as exc:
            await self._mark(session, order, "UNKNOWN")
            raise OrderTimeoutError(
                f"Upbit place_order timed out for order {order.id} - reconcile before retrying "
                "(Upbit has no verified idempotency key, so this may or may not have gone through)",
                client_order_id=order.id,
            ) from exc
        except UpbitApiError:
            await self._mark(session, order, "REJECTED")
            raise

        order.broker_order_id = result.get("uuid") if isinstance(result, dict) else None
        await self._mark(session, order, _map_upbit_state(result.get("state")) if isinstance(result, dict) else "SUBMITTED")
        return order

    async def cancel_order(self, session: AsyncSession, *, order: Order) -> Order:
        self._require_live_trading()
        if order.broker_order_id is None:
            raise ValueError("Cannot cancel an order with no broker_order_id - reconcile first")

        result = await self._orders.cancel_order(order.broker_order_id)
        await self._mark(
            session, order, _map_upbit_state(result.get("state")) if isinstance(result, dict) else "CANCELLED"
        )
        return order

    async def get_status(self, order: Order) -> dict[str, Any]:
        """Live broker-reported status for an order that already has a
        `broker_order_id` - does not touch the local row (callers decide
        whether/how to persist)."""
        if order.broker_order_id is None:
            raise ValueError("Cannot query status for an order with no broker_order_id")
        return await self._orders.get_order(order.broker_order_id)

    async def reconcile_order(self, session: AsyncSession, *, order: Order) -> Order:
        """Best-effort recovery for an order left in `PENDING`/`UNKNOWN` by a
        timeout. Without a verified idempotency key (see module docstring),
        this can only search recent orders for this market by side/volume/
        price - a heuristic, not a guarantee. Never places a new order;
        only updates this row's status from what the broker reports, or
        leaves it `UNKNOWN` if no confident match is found.
        """
        if order.status not in ("PENDING", "UNKNOWN"):
            return order

        candidates: list[dict[str, Any]] = []
        for state in ("wait", "watch", "done", "cancel"):
            candidates.extend(await self._orders.list_orders(market=order.symbol, state=state))

        match = self._find_match(order, candidates)
        if match is not None:
            order.broker_order_id = match.get("uuid")
            await self._mark(session, order, _map_upbit_state(match.get("state")))
        return order

    @staticmethod
    def _find_match(order: Order, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        upbit_side = _SIDE_TO_UPBIT.get(order.side)
        for candidate in candidates:
            if candidate.get("side") != upbit_side:
                continue
            if _quantity_matches(candidate.get("volume"), order.quantity):
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
