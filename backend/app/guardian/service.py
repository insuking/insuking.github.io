"""Position Guardian orchestration (P16).

Ties the pure decision functions in this package into one per-position
"tick": given a position's current market context, decide whether to exit
on a failed breakout or tighten its trailing stop - and persist that
decision as `ProtectiveOrder`/`Position` row updates.

This does **not** itself call a broker execution provider (P15) - it
decides and records what protection *should* look like; turning that into
a real order is the job of whatever process actually drives the tick (a
scheduled job, which doesn't exist anywhere in this repository yet - see
P19's watchdog). Keeping that boundary here mirrors P14's
`revalidate()`/`apply_revalidation_result()` split: decide, then record,
with order placement staying a deliberate, separate step nothing calls
automatically.

Quantity/percentage state derivation (T1_FILLED/T2_FILLED/RUNNER driven by
actual fills) is P17's job - see protective_orders.py's module docstring
for the exact split.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Position, ProtectiveOrder, TradePlan
from app.guardian.failed_breakout import should_exit_on_failed_breakout
from app.guardian.protective_orders import initial_protective_orders
from app.guardian.trailing import trailing_stop_price
from app.models.domain import Candle, PositionState
from app.radar.state import RadarState


class GuardianActionType(str, Enum):
    OK = "OK"
    NO_ACTIVE_STOP = "NO_ACTIVE_STOP"
    GUARDIAN_INACTIVE = "GUARDIAN_INACTIVE"
    EXIT_FAILED_BREAKOUT = "EXIT_FAILED_BREAKOUT"
    TIGHTENED_STOP = "TIGHTENED_STOP"


@dataclass
class GuardianAction:
    action: GuardianActionType
    detail: str | None = None


class PositionGuardianService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_initial_orders(
        self, position: Position, trade_plan: TradePlan
    ) -> list[ProtectiveOrder]:
        """Creates the STOP/T1/T2 protective order rows for a freshly
        opened position. Idempotent - a position that already has
        protective orders is returned as-is rather than duplicated."""
        existing = await self._active_orders(position)
        if existing:
            return existing

        now = datetime.now(UTC)
        rows = [
            ProtectiveOrder(
                id=str(uuid.uuid4()),
                position_id=position.id,
                kind=spec.kind,
                trigger_price=spec.trigger_price,
                quantity=spec.quantity,
                active=True,
                created_at=now,
                updated_at=now,
            )
            for spec in initial_protective_orders(trade_plan)
        ]
        for row in rows:
            self._session.add(row)
        await self._session.commit()
        return rows

    async def process_position(
        self,
        position: Position,
        radar_state: RadarState,
        recent_candles: list[Candle],
    ) -> GuardianAction:
        if not position.guardian_active:
            return GuardianAction(GuardianActionType.GUARDIAN_INACTIVE)

        if should_exit_on_failed_breakout(PositionState(position.state), radar_state):
            await self._deactivate_all(position)
            position.state = PositionState.CLOSED.value
            position.updated_at = datetime.now(UTC)
            await self._session.commit()
            return GuardianAction(GuardianActionType.EXIT_FAILED_BREAKOUT)

        stop_order = await self._active_stop(position)
        if stop_order is None:
            return GuardianAction(GuardianActionType.NO_ACTIVE_STOP)

        new_stop = trailing_stop_price(recent_candles, stop_order.trigger_price)
        if new_stop > stop_order.trigger_price:
            stop_order.trigger_price = new_stop
            stop_order.updated_at = datetime.now(UTC)
            position.stop_price = new_stop
            position.updated_at = datetime.now(UTC)
            await self._session.commit()
            return GuardianAction(GuardianActionType.TIGHTENED_STOP, f"stop tightened to {new_stop:g}")

        return GuardianAction(GuardianActionType.OK)

    async def _active_orders(self, position: Position) -> list[ProtectiveOrder]:
        result = await self._session.execute(
            select(ProtectiveOrder).where(
                ProtectiveOrder.position_id == position.id, ProtectiveOrder.active.is_(True)
            )
        )
        return list(result.scalars().all())

    async def _active_stop(self, position: Position) -> ProtectiveOrder | None:
        result = await self._session.execute(
            select(ProtectiveOrder).where(
                ProtectiveOrder.position_id == position.id,
                ProtectiveOrder.kind == "STOP",
                ProtectiveOrder.active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def _deactivate_all(self, position: Position) -> None:
        for row in await self._active_orders(position):
            row.active = False
            row.updated_at = datetime.now(UTC)
