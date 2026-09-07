from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.db.models import SystemHealthRow
from app.db.session import session_scope
from app.guardian.health import SERVICE_NAME, is_stale, record_heartbeat, should_block_new_trades
from app.models.domain import HealthState

pytestmark = pytest.mark.P16


def test_should_block_new_trades_only_when_not_healthy() -> None:
    assert should_block_new_trades(HealthState.HEALTHY) is False
    assert should_block_new_trades(HealthState.DEGRADED) is True
    assert should_block_new_trades(HealthState.RECOVERING) is True
    assert should_block_new_trades(HealthState.PAUSED) is True
    assert should_block_new_trades(HealthState.CRITICAL) is True
    assert should_block_new_trades(HealthState.OFFLINE) is True


def test_is_stale_true_past_max_age() -> None:
    last = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    now = last + timedelta(seconds=61)
    assert is_stale(last, now, max_age_seconds=60) is True


def test_is_stale_false_within_max_age() -> None:
    last = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    now = last + timedelta(seconds=59)
    assert is_stale(last, now, max_age_seconds=60) is False


@pytest.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(SystemHealthRow).where(SystemHealthRow.service == SERVICE_NAME))
        await session.commit()


@pytest.mark.asyncio
async def test_record_heartbeat_persists_state_and_message() -> None:
    async with session_scope() as session:
        row = await record_heartbeat(session, state=HealthState.DEGRADED, message="ws reconnecting")

        result = await session.execute(select(SystemHealthRow).where(SystemHealthRow.id == row.id))
        persisted = result.scalar_one()

    assert persisted.service == SERVICE_NAME
    assert persisted.state == "DEGRADED"
    assert persisted.message == "ws reconnecting"


@pytest.mark.asyncio
async def test_record_heartbeat_defaults_to_healthy() -> None:
    async with session_scope() as session:
        row = await record_heartbeat(session)
    assert row.state == "HEALTHY"
