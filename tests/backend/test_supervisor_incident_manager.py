"""P19 acceptance: incident_manager.py against the real local Postgres,
proving the full lifecycle (open -> record attempts -> mark recovered) and
that `human_action_required` matches the failure's classification.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from app.db.models import Incident
from app.db.session import session_scope
from app.supervisor.failure_classifier import FailureType
from app.supervisor.incident_manager import (
    mark_recovered,
    open_incident,
    open_unresolved_incidents,
    record_recovery_attempt,
)

pytestmark = [pytest.mark.P19, pytest.mark.asyncio]

_SERVICE = "test-supervisor-incident-manager"


@pytest.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(Incident).where(Incident.service == _SERVICE))
        await session.commit()


async def test_open_incident_for_auto_recoverable_failure_does_not_require_human_action() -> None:
    async with session_scope() as session:
        incident = await open_incident(
            session,
            service=_SERVICE,
            severity="LOW",
            failure_type=FailureType.WEBSOCKET_DISCONNECT,
            safe_action="attempting automatic recovery",
        )

    assert incident.human_action_required is False
    assert incident.failure_type == "WEBSOCKET_DISCONNECT"
    assert incident.recovery_attempts == 0
    assert incident.recovered_at is None


async def test_open_incident_for_never_auto_resolved_failure_requires_human_action() -> None:
    async with session_scope() as session:
        incident = await open_incident(
            session,
            service=_SERVICE,
            severity="HIGH",
            failure_type=FailureType.POSITION_MISMATCH,
            safe_action="new trades blocked pending manual review",
        )

    assert incident.human_action_required is True


async def test_record_recovery_attempt_increments_counter() -> None:
    async with session_scope() as session:
        incident = await open_incident(
            session, service=_SERVICE, severity="LOW", failure_type=FailureType.API_TIMEOUT
        )
        incident = await record_recovery_attempt(session, incident)
        incident = await record_recovery_attempt(session, incident)

    assert incident.recovery_attempts == 2


async def test_mark_recovered_sets_timestamp_and_verification_result() -> None:
    async with session_scope() as session:
        incident = await open_incident(
            session, service=_SERVICE, severity="LOW", failure_type=FailureType.DB_CONNECTION_RESET
        )
        assert incident.recovered_at is None

        incident = await mark_recovered(session, incident, verification_result="VERIFIED")

    assert incident.recovered_at is not None
    assert incident.recovered_at.tzinfo is not None
    assert incident.verification_result == "VERIFIED"


async def test_open_unresolved_incidents_excludes_recovered() -> None:
    async with session_scope() as session:
        unresolved = await open_incident(
            session, service=_SERVICE, severity="LOW", failure_type=FailureType.CONSUMER_LAG
        )
        resolved = await open_incident(
            session, service=_SERVICE, severity="LOW", failure_type=FailureType.STALE_CACHE
        )
        await mark_recovered(session, resolved, verification_result="VERIFIED")

        found = await open_unresolved_incidents(session, service=_SERVICE)

    found_ids = {incident.id for incident in found}
    assert unresolved.id in found_ids
    assert resolved.id not in found_ids


async def test_open_unresolved_incidents_filters_by_service() -> None:
    other_service = f"{_SERVICE}-other"
    async with session_scope() as session:
        await open_incident(
            session, service=_SERVICE, severity="LOW", failure_type=FailureType.PROCESS_CRASH
        )
        await open_incident(
            session, service=other_service, severity="LOW", failure_type=FailureType.PROCESS_CRASH
        )

        found = await open_unresolved_incidents(session, service=_SERVICE)

    assert all(incident.service == _SERVICE for incident in found)

    async with session_scope() as session:
        await session.execute(delete(Incident).where(Incident.service == other_service))
        await session.commit()


async def test_open_incident_records_detected_at_close_to_now() -> None:
    before = datetime.now(UTC)
    async with session_scope() as session:
        incident = await open_incident(
            session, service=_SERVICE, severity="LOW", failure_type=FailureType.TEMPORARY_DNS_FAILURE
        )
    after = datetime.now(UTC)

    assert before <= incident.detected_at <= after
