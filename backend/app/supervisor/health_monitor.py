"""System-wide health aggregation (P19 DETECT step).

Reuses each already-built health probe rather than reimplementing them:
`app.db.session.check_database` (P2), `app.db.redis_client.check_redis`
(P2), and Guardian's own heartbeat staleness check
(`app.guardian.health.is_stale`, P16). This module's only job is rolling
those up into one `HealthState` per service and an overall system verdict
- "critical unknown states pause the system" (docs/MASTER_SPEC.md section
L-R) means a service with no recorded heartbeat at all is `OFFLINE`, not
silently assumed healthy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SystemHealthRow
from app.db.redis_client import check_redis
from app.db.session import check_database
from app.guardian.health import DEFAULT_MAX_HEARTBEAT_AGE_SECONDS, is_stale
from app.guardian.health import SERVICE_NAME as GUARDIAN_SERVICE
from app.models.domain import HealthState

# Worst-to-best is the wrong order for `max()` below (HEALTHY should not
# "win") - this lists best-to-worst so a higher index always means worse.
_SEVERITY_ORDER = [
    HealthState.HEALTHY,
    HealthState.DEGRADED,
    HealthState.RECOVERING,
    HealthState.PAUSED,
    HealthState.CRITICAL,
    HealthState.OFFLINE,
]


@dataclass
class ServiceHealth:
    service: str
    state: HealthState
    detail: str | None = None


async def check_database_health() -> ServiceHealth:
    ok = await check_database()
    return ServiceHealth("database", HealthState.HEALTHY if ok else HealthState.OFFLINE)


async def check_redis_health() -> ServiceHealth:
    ok = await check_redis()
    return ServiceHealth("redis", HealthState.HEALTHY if ok else HealthState.OFFLINE)


async def check_guardian_health(
    session: AsyncSession,
    now: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_HEARTBEAT_AGE_SECONDS,
) -> ServiceHealth:
    result = await session.execute(
        select(SystemHealthRow)
        .where(SystemHealthRow.service == GUARDIAN_SERVICE)
        .order_by(SystemHealthRow.detected_at.desc())
        .limit(1)
    )
    latest = result.scalar_one_or_none()
    now = now or datetime.now(UTC)

    if latest is None:
        return ServiceHealth(GUARDIAN_SERVICE, HealthState.OFFLINE, "no heartbeat recorded yet")
    if is_stale(latest.detected_at, now, max_age_seconds):
        return ServiceHealth(GUARDIAN_SERVICE, HealthState.CRITICAL, "heartbeat stale")
    return ServiceHealth(GUARDIAN_SERVICE, HealthState(latest.state), latest.message)


def overall_state(service_healths: list[ServiceHealth]) -> HealthState:
    """The single worst reported state wins - a system is only as healthy
    as its least healthy service. No services checked at all is treated as
    `OFFLINE` (uncertain, not "assume fine")."""
    if not service_healths:
        return HealthState.OFFLINE
    return max(service_healths, key=lambda sh: _SEVERITY_ORDER.index(sh.state)).state
