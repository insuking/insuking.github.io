"""Risk state persistence (P18).

Bridges P1's `RiskState` domain model to the append-only `risk_states`
table (see app/db/models.py's `RiskStateRow`) - "current" risk state means
the latest row by `as_of`, the same convention `system_health` already
uses for Guardian's heartbeat.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RiskStateRow
from app.models.domain import RiskState


async def record_risk_state(session: AsyncSession, risk_state: RiskState) -> RiskStateRow:
    row = RiskStateRow(
        id=str(uuid.uuid4()),
        as_of=risk_state.as_of,
        daily_loss=risk_state.daily_loss,
        daily_loss_limit=risk_state.daily_loss_limit,
        exposure=risk_state.exposure,
        exposure_limit=risk_state.exposure_limit,
        open_positions=risk_state.open_positions,
        max_positions=risk_state.max_positions,
        consecutive_stops=risk_state.consecutive_stops,
        kill_switch_active=risk_state.kill_switch_active,
        kill_switch_reason=risk_state.kill_switch_reason,
    )
    session.add(row)
    await session.commit()
    return row


async def latest_risk_state(session: AsyncSession) -> RiskStateRow | None:
    result = await session.execute(select(RiskStateRow).order_by(RiskStateRow.as_of.desc()).limit(1))
    return result.scalar_one_or_none()
