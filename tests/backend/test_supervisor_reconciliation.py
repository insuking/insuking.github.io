"""P19 acceptance: reconciliation.py turns P16's position mismatches into
open `Incident` rows against real local Postgres - position mismatch and
unexpected broker holdings both must require human action, matching
docs/MASTER_SPEC.md's never-auto-resolved list.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.models import Incident, Position
from app.db.session import session_scope
from app.guardian.position_sync import BrokerHolding
from app.supervisor.failure_classifier import FailureType
from app.supervisor.reconciliation import reconcile_positions

pytestmark = [pytest.mark.P19, pytest.mark.asyncio]

_SERVICE = "test-supervisor-reconciliation"
NOW = datetime.now(UTC)


def _position(symbol: str, quantity: float) -> Position:
    return Position(
        id=f"recon-pos-{symbol}",
        symbol=symbol,
        asset_type="CRYPTO",
        quantity=quantity,
        avg_entry_price=100.0,
        stop_price=90.0,
        state="OPEN",
        guardian_active=True,
        opened_at=NOW,
        updated_at=NOW,
    )


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(Incident).where(Incident.service == _SERVICE))
        await session.commit()


async def test_no_incidents_when_positions_agree() -> None:
    local = [_position("KRW-XRP", 100.0)]
    broker = [BrokerHolding("KRW-XRP", 100.0)]

    async with session_scope() as session:
        incidents = await reconcile_positions(session, local, broker, service=_SERVICE)

    assert incidents == []


async def test_quantity_mismatch_opens_position_mismatch_incident() -> None:
    local = [_position("KRW-XRP", 100.0)]
    broker = [BrokerHolding("KRW-XRP", 70.0)]

    async with session_scope() as session:
        incidents = await reconcile_positions(session, local, broker, service=_SERVICE)

    assert len(incidents) == 1
    assert incidents[0].failure_type == FailureType.POSITION_MISMATCH.value
    assert incidents[0].human_action_required is True
    assert incidents[0].service == _SERVICE
    assert "KRW-XRP" in (incidents[0].safe_action or "")


async def test_missing_at_broker_opens_position_mismatch_incident() -> None:
    local = [_position("KRW-XRP", 100.0)]
    broker: list[BrokerHolding] = []

    async with session_scope() as session:
        incidents = await reconcile_positions(session, local, broker, service=_SERVICE)

    assert len(incidents) == 1
    assert incidents[0].failure_type == FailureType.POSITION_MISMATCH.value
    assert incidents[0].human_action_required is True


async def test_missing_locally_opens_unexpected_broker_holdings_incident() -> None:
    local: list[Position] = []
    broker = [BrokerHolding("KRW-DOGE", 50.0)]

    async with session_scope() as session:
        incidents = await reconcile_positions(session, local, broker, service=_SERVICE)

    assert len(incidents) == 1
    assert incidents[0].failure_type == FailureType.UNEXPECTED_BROKER_HOLDINGS.value
    assert incidents[0].human_action_required is True


async def test_multiple_mismatches_open_multiple_incidents() -> None:
    local = [_position("KRW-XRP", 100.0)]
    broker = [BrokerHolding("KRW-XRP", 70.0), BrokerHolding("KRW-DOGE", 50.0)]

    async with session_scope() as session:
        incidents = await reconcile_positions(session, local, broker, service=_SERVICE)

    assert len(incidents) == 2
