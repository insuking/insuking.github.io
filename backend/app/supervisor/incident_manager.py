"""Incident tracking (P19).

CRUD over `app.db.models.Incident` (already created in P2, unused until
now) - the audit trail docs/MASTER_SPEC.md section L-R requires: "Every
incident records: id, service, severity, failure_type, detected_at,
safe_action, recovery_attempts, recovered_at, verification_result,
human_action_required."
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Incident
from app.supervisor.failure_classifier import FailureType, requires_human_action


async def open_incident(
    session: AsyncSession,
    *,
    service: str,
    severity: str,
    failure_type: FailureType,
    safe_action: str | None = None,
) -> Incident:
    incident = Incident(
        id=str(uuid.uuid4()),
        service=service,
        severity=severity,
        failure_type=failure_type.value,
        detected_at=datetime.now(UTC),
        safe_action=safe_action,
        recovery_attempts=0,
        human_action_required=requires_human_action(failure_type),
    )
    session.add(incident)
    await session.commit()
    return incident


async def record_recovery_attempt(session: AsyncSession, incident: Incident) -> Incident:
    incident.recovery_attempts += 1
    await session.commit()
    return incident


async def mark_recovered(session: AsyncSession, incident: Incident, verification_result: str) -> Incident:
    incident.recovered_at = datetime.now(UTC)
    incident.verification_result = verification_result
    await session.commit()
    return incident


async def open_unresolved_incidents(session: AsyncSession, service: str | None = None) -> list[Incident]:
    query = select(Incident).where(Incident.recovered_at.is_(None))
    if service is not None:
        query = query.where(Incident.service == service)
    result = await session.execute(query)
    return list(result.scalars().all())
