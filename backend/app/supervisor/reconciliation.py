"""Reconciliation (P19 DIAGNOSE step for account/order/position integrity).

Never invents a fix or guesses - reuses what P16 already built
(`app.guardian.position_sync.find_position_mismatches`) and turns whatever
it finds into an open `Incident`. Per docs/MASTER_SPEC.md, position
mismatch and unexpected broker holdings are both on the "never
auto-resolved" list, so finding either here always raises an incident
requiring human review; this module has no recovery path of its own to
attempt, unlike the auto-recoverable failures `recovery_manager.py` handles.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Incident, Position
from app.guardian.position_sync import BrokerHolding, MismatchKind, find_position_mismatches
from app.supervisor.failure_classifier import FailureType
from app.supervisor.incident_manager import open_incident

_MISMATCH_TO_FAILURE_TYPE = {
    MismatchKind.QUANTITY_MISMATCH: FailureType.POSITION_MISMATCH,
    MismatchKind.MISSING_AT_BROKER: FailureType.POSITION_MISMATCH,
    MismatchKind.MISSING_LOCALLY: FailureType.UNEXPECTED_BROKER_HOLDINGS,
}


async def reconcile_positions(
    session: AsyncSession,
    local_positions: list[Position],
    broker_holdings: list[BrokerHolding],
    service: str,
) -> list[Incident]:
    mismatches = find_position_mismatches(local_positions, broker_holdings)
    incidents = []
    for mismatch in mismatches:
        incident = await open_incident(
            session,
            service=service,
            severity="HIGH",
            failure_type=_MISMATCH_TO_FAILURE_TYPE[mismatch.kind],
            safe_action=(
                f"new trades blocked pending manual review of {mismatch.symbol} "
                f"(local={mismatch.local_quantity}, broker={mismatch.broker_quantity})"
            ),
        )
        incidents.append(incident)
    return incidents
