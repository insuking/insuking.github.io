"""P18 acceptance: RiskService against the real local Postgres (like
test_guardian_service.py) - proving risk snapshots actually persist and
that should_block_new_trades reads back what was last recorded.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.models import RiskStateRow
from app.db.session import session_scope
from app.models.domain import RiskState
from app.risk.kill_switch import RiskContext
from app.risk.service import RiskService

pytestmark = [pytest.mark.P18, pytest.mark.asyncio]


def _risk_state(as_of: datetime, **overrides: object) -> RiskState:
    defaults: dict[str, object] = {
        "as_of": as_of,
        "daily_loss": 0.0,
        "daily_loss_limit": 100000.0,
        "exposure": 0.0,
        "exposure_limit": 500000.0,
        "open_positions": 0,
        "max_positions": 5,
        "consecutive_stops": 0,
    }
    defaults.update(overrides)
    return RiskState(**defaults)  # type: ignore[arg-type]


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    cutoff = datetime.now(UTC)
    yield
    async with session_scope() as session:
        await session.execute(delete(RiskStateRow).where(RiskStateRow.as_of >= cutoff))
        await session.commit()


async def test_evaluate_and_record_persists_clean_state() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        service = RiskService(session)
        row, report = await service.evaluate_and_record(RiskContext(risk_state=_risk_state(now)))

    assert report.active is False
    assert row.kill_switch_active is False
    assert row.kill_switch_reason is None


async def test_evaluate_and_record_persists_triggered_reasons() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        service = RiskService(session)
        context = RiskContext(risk_state=_risk_state(now), market_crash=True, unknown_order=True)
        row, report = await service.evaluate_and_record(context)

    assert report.active is True
    assert row.kill_switch_active is True
    assert row.kill_switch_reason is not None
    assert "crash" in row.kill_switch_reason
    assert "UNKNOWN" in row.kill_switch_reason


async def test_should_block_new_trades_false_after_clean_evaluation() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        service = RiskService(session)
        await service.evaluate_and_record(RiskContext(risk_state=_risk_state(now)))
        blocked = await service.should_block_new_trades()

    assert blocked is False


async def test_should_block_new_trades_true_after_triggered_evaluation() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        service = RiskService(session)
        await service.evaluate_and_record(RiskContext(risk_state=_risk_state(now), guardian_healthy=False))
        blocked = await service.should_block_new_trades()

    assert blocked is True


async def test_should_block_new_trades_uses_most_recent_evaluation() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        service = RiskService(session)
        await service.evaluate_and_record(RiskContext(risk_state=_risk_state(now), guardian_healthy=False))
        await service.evaluate_and_record(
            RiskContext(risk_state=_risk_state(now + timedelta(seconds=1)))
        )
        blocked = await service.should_block_new_trades()

    assert blocked is False
