"""P19 acceptance: recovery_manager.py's full DETECT->CLASSIFY->SAFE
STATE->DIAGNOSE->RECOVER->VERIFY->RESUME OR REMAIN PAUSED flow, against
real local Postgres for the incident persistence and stub callables for the
service-specific recover/verify actions.
"""

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.models import Incident
from app.db.session import session_scope
from app.models.domain import HealthState
from app.supervisor.failure_classifier import FailureType
from app.supervisor.recovery_manager import handle_failure

pytestmark = [pytest.mark.P19, pytest.mark.asyncio]

_SERVICE = "test-supervisor-recovery-manager"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(Incident).where(Incident.service == _SERVICE))
        await session.commit()


async def test_never_auto_resolved_failure_pauses_without_attempting_recovery() -> None:
    recover_calls = {"count": 0}

    async def recover() -> bool:
        recover_calls["count"] += 1
        return True

    async with session_scope() as session:
        outcome = await handle_failure(
            session,
            service=_SERVICE,
            failure_type=FailureType.POSITION_MISMATCH,
            severity="HIGH",
            recover=recover,
        )

    assert outcome.resulting_state == HealthState.PAUSED
    assert outcome.incident.human_action_required is True
    assert outcome.incident.recovered_at is None
    assert outcome.incident.recovery_attempts == 0
    assert recover_calls["count"] == 0


async def test_auto_recoverable_failure_with_no_recover_callable_is_degraded() -> None:
    async with session_scope() as session:
        outcome = await handle_failure(
            session,
            service=_SERVICE,
            failure_type=FailureType.WEBSOCKET_DISCONNECT,
            severity="LOW",
        )

    assert outcome.resulting_state == HealthState.DEGRADED
    assert outcome.incident.human_action_required is False
    assert outcome.incident.recovered_at is None


async def test_auto_recoverable_failure_recovers_and_verifies_to_healthy() -> None:
    async def recover() -> bool:
        return True

    async def verify() -> bool:
        return True

    async with session_scope() as session:
        outcome = await handle_failure(
            session,
            service=_SERVICE,
            failure_type=FailureType.DB_CONNECTION_RESET,
            severity="LOW",
            recover=recover,
            verify=verify,
        )

    assert outcome.resulting_state == HealthState.HEALTHY
    assert outcome.incident.recovered_at is not None
    assert outcome.incident.verification_result == "VERIFIED"
    assert outcome.incident.recovery_attempts == 1


async def test_auto_recoverable_failure_exhausts_attempts_when_recover_always_fails() -> None:
    async def recover() -> bool:
        return False

    async with session_scope() as session:
        outcome = await handle_failure(
            session,
            service=_SERVICE,
            failure_type=FailureType.API_TIMEOUT,
            severity="LOW",
            recover=recover,
            max_attempts=3,
        )

    assert outcome.resulting_state == HealthState.CRITICAL
    assert outcome.incident.recovered_at is None
    assert outcome.incident.recovery_attempts == 3


async def test_auto_recoverable_failure_exhausts_attempts_when_verify_always_fails() -> None:
    async def recover() -> bool:
        return True

    async def verify() -> bool:
        return False

    async with session_scope() as session:
        outcome = await handle_failure(
            session,
            service=_SERVICE,
            failure_type=FailureType.TRANSIENT_REDIS_FAILURE,
            severity="LOW",
            recover=recover,
            verify=verify,
            max_attempts=2,
        )

    assert outcome.resulting_state == HealthState.CRITICAL
    assert outcome.incident.recovered_at is None
    assert outcome.incident.recovery_attempts == 2


async def test_auto_recoverable_failure_succeeds_on_a_later_attempt() -> None:
    calls = {"count": 0}

    async def recover() -> bool:
        calls["count"] += 1
        return calls["count"] >= 2

    async def verify() -> bool:
        return True

    async with session_scope() as session:
        outcome = await handle_failure(
            session,
            service=_SERVICE,
            failure_type=FailureType.PROCESS_CRASH,
            severity="LOW",
            recover=recover,
            verify=verify,
            max_attempts=3,
        )

    assert outcome.resulting_state == HealthState.HEALTHY
    assert outcome.incident.recovery_attempts == 2


async def test_recover_raising_is_treated_as_a_failed_attempt_not_a_crash() -> None:
    async def recover() -> bool:
        raise RuntimeError("network unreachable")

    async with session_scope() as session:
        outcome = await handle_failure(
            session,
            service=_SERVICE,
            failure_type=FailureType.API_TIMEOUT,
            severity="LOW",
            recover=recover,
            max_attempts=2,
        )

    assert outcome.resulting_state == HealthState.CRITICAL
    assert outcome.incident.recovery_attempts == 2
