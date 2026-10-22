"""Position Guardian health/heartbeat (P16).

Per docs/MASTER_SPEC.md: "a Guardian crash turns new buys off." This
records Guardian's own health into the same `system_health` table P2
already created for exactly this purpose (`app.db.models.SystemHealthRow`),
using P1's `HealthState` vocabulary - P18 (risk + kill switch, not built
yet) is what actually reads this to gate new trade approval; this module
only produces the signal, honestly, rather than pretending to enforce the
gate itself (P16 has no order-approval code to gate).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SystemHealthRow
from app.models.domain import HealthState

SERVICE_NAME = "position_guardian"
DEFAULT_MAX_HEARTBEAT_AGE_SECONDS = 60


async def record_heartbeat(
    session: AsyncSession, state: HealthState = HealthState.HEALTHY, message: str | None = None
) -> SystemHealthRow:
    row = SystemHealthRow(
        id=str(uuid.uuid4()),
        service=SERVICE_NAME,
        state=state.value,
        detected_at=datetime.now(UTC),
        message=message,
    )
    session.add(row)
    await session.commit()
    return row


def is_stale(last_heartbeat_at: datetime, now: datetime, max_age_seconds: int = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS) -> bool:
    return (now - last_heartbeat_at).total_seconds() > max_age_seconds


def should_block_new_trades(state: HealthState) -> bool:
    """Only a fully `HEALTHY` Guardian may wave through new trades - every
    other state (including `RECOVERING`) blocks new buys while existing
    protection keeps running, per docs/MASTER_SPEC.md's Final Instruction:
    "if... Guardian health... is uncertain, block new trades." Protecting
    already-open positions is not gated by this - only new entries are.
    """
    return state != HealthState.HEALTHY
