"""Partial profit engine orchestration (P17).

Syncs a `Position` row (P2) to whatever `compute_position_accounting`
(accounting.py) derives from a set of fills - the DB-integration half of
"state derived from actual fills, never assumed requested fill." This is
the only place a `Position`'s `quantity`/`avg_entry_price`/`state` should
be written once it's open; nothing here places or assumes an order filled
on its own - fills come from whatever already recorded them (P15's
execution providers reconciling broker state, or a manual entry today,
since there is no live fill-listening pipeline in this codebase yet).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Position, TradePlan
from app.partial_profit.accounting import FillEvent, PositionAccounting, compute_position_accounting


class PartialProfitService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sync_position_from_fills(
        self, position: Position, trade_plan: TradePlan, fills: list[FillEvent]
    ) -> tuple[Position, PositionAccounting]:
        accounting = compute_position_accounting(trade_plan, fills)

        position.quantity = accounting.remaining_qty
        if accounting.filled_entry_qty > 0:
            position.avg_entry_price = accounting.avg_entry_price
        position.state = accounting.state.value
        position.updated_at = datetime.now(UTC)
        await self._session.commit()

        return position, accounting
