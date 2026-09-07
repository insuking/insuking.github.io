"""P19 acceptance: health_monitor.py's DB/Redis probes against real local
infra, Guardian heartbeat aggregation against real local Postgres, and the
pure `overall_state` severity roll-up.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.db.models import SystemHealthRow
from app.db.session import session_scope
from app.guardian.health import SERVICE_NAME as GUARDIAN_SERVICE
from app.guardian.health import record_heartbeat
from app.models.domain import HealthState
from app.supervisor.health_monitor import (
    ServiceHealth,
    check_database_health,
    check_guardian_health,
    check_redis_health,
    overall_state,
)

pytestmark = pytest.mark.P19


@pytest.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(SystemHealthRow).where(SystemHealthRow.service == GUARDIAN_SERVICE))
        await session.commit()


async def test_check_database_health_is_healthy_against_real_db() -> None:
    health = await check_database_health()
    assert health.service == "database"
    assert health.state == HealthState.HEALTHY


async def test_check_redis_health_is_healthy_against_real_redis() -> None:
    health = await check_redis_health()
    assert health.service == "redis"
    assert health.state == HealthState.HEALTHY


async def test_check_guardian_health_offline_when_no_heartbeat_recorded() -> None:
    async with session_scope() as session:
        health = await check_guardian_health(session)

    assert health.state == HealthState.OFFLINE
    assert health.detail == "no heartbeat recorded yet"


async def test_check_guardian_health_reflects_latest_heartbeat_state() -> None:
    async with session_scope() as session:
        await record_heartbeat(session, state=HealthState.DEGRADED, message="ws reconnecting")
        health = await check_guardian_health(session)

    assert health.state == HealthState.DEGRADED
    assert health.detail == "ws reconnecting"


async def test_check_guardian_health_critical_when_heartbeat_stale() -> None:
    async with session_scope() as session:
        await record_heartbeat(session, state=HealthState.HEALTHY)
        far_future = datetime.now(UTC) + timedelta(hours=1)
        health = await check_guardian_health(session, now=far_future, max_age_seconds=60)

    assert health.state == HealthState.CRITICAL
    assert health.detail == "heartbeat stale"


async def test_check_guardian_health_uses_most_recent_heartbeat() -> None:
    async with session_scope() as session:
        await record_heartbeat(session, state=HealthState.DEGRADED)
        await record_heartbeat(session, state=HealthState.HEALTHY)
        health = await check_guardian_health(session)

    assert health.state == HealthState.HEALTHY


def test_overall_state_empty_list_is_offline() -> None:
    assert overall_state([]) == HealthState.OFFLINE


def test_overall_state_all_healthy_is_healthy() -> None:
    healths = [ServiceHealth("a", HealthState.HEALTHY), ServiceHealth("b", HealthState.HEALTHY)]
    assert overall_state(healths) == HealthState.HEALTHY


def test_overall_state_picks_worst_of_mixed_states() -> None:
    healths = [
        ServiceHealth("database", HealthState.HEALTHY),
        ServiceHealth("redis", HealthState.DEGRADED),
        ServiceHealth("guardian", HealthState.CRITICAL),
    ]
    assert overall_state(healths) == HealthState.CRITICAL


def test_overall_state_offline_outranks_critical() -> None:
    healths = [ServiceHealth("a", HealthState.CRITICAL), ServiceHealth("b", HealthState.OFFLINE)]
    assert overall_state(healths) == HealthState.OFFLINE
