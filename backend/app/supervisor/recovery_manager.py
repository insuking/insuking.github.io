"""Recovery orchestration (P19).

Ties the rest of `app/supervisor/` into the full
docs/MASTER_SPEC.md section L-R flow: `DETECT -> CLASSIFY -> SAFE STATE ->
DIAGNOSE -> RECOVER -> VERIFY -> RESUME OR REMAIN PAUSED`.

- CLASSIFY: `failure_classifier.is_auto_recoverable`.
- Never-auto-resolved failures skip straight to SAFE STATE: an incident is
  opened (`human_action_required=True`), no recovery is attempted, and the
  result is `PAUSED` - matching the "never done by the self-healing
  engine" list (never guesses, never places an order, never widens a
  stop-loss to "fix" something).
- Auto-recoverable failures get a bounded number of RECOVER attempts (via
  a caller-supplied `recover` callable - this module doesn't know how to
  fix any specific service, only how to run and account for the attempt;
  see service_restart.py for the actual recovery actions) each followed by
  VERIFY (self_test.verify_recovery). The first attempt that both succeeds
  and verifies marks the incident recovered and returns `HEALTHY`;
  exhausting all attempts returns `CRITICAL` rather than pretending
  recovery worked.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Incident
from app.models.domain import HealthState
from app.supervisor.failure_classifier import FailureType, is_auto_recoverable
from app.supervisor.incident_manager import mark_recovered, open_incident, record_recovery_attempt
from app.supervisor.self_test import verify_recovery

DEFAULT_MAX_RECOVERY_ATTEMPTS = 3


@dataclass
class RecoveryOutcome:
    incident: Incident
    resulting_state: HealthState


async def _always_true() -> bool:
    return True


async def handle_failure(
    session: AsyncSession,
    *,
    service: str,
    failure_type: FailureType,
    severity: str,
    recover: Callable[[], Awaitable[bool]] | None = None,
    verify: Callable[[], Awaitable[bool]] | None = None,
    max_attempts: int = DEFAULT_MAX_RECOVERY_ATTEMPTS,
) -> RecoveryOutcome:
    if not is_auto_recoverable(failure_type):
        incident = await open_incident(
            session,
            service=service,
            severity=severity,
            failure_type=failure_type,
            safe_action="new trades blocked pending manual review",
        )
        return RecoveryOutcome(incident=incident, resulting_state=HealthState.PAUSED)

    incident = await open_incident(
        session,
        service=service,
        severity=severity,
        failure_type=failure_type,
        safe_action="attempting automatic recovery",
    )

    if recover is None:
        # Classified as recoverable, but no recovery action was provided -
        # honest DEGRADED (not HEALTHY, not PAUSED) rather than guessing.
        return RecoveryOutcome(incident=incident, resulting_state=HealthState.DEGRADED)

    probe = verify or _always_true
    for _ in range(max_attempts):
        await record_recovery_attempt(session, incident)
        try:
            recovered = await recover()
        except Exception:  # noqa: BLE001 - a failing recovery attempt is data, not a crash
            recovered = False

        if recovered and await verify_recovery(probe):
            await mark_recovered(session, incident, verification_result="VERIFIED")
            return RecoveryOutcome(incident=incident, resulting_state=HealthState.HEALTHY)

    return RecoveryOutcome(incident=incident, resulting_state=HealthState.CRITICAL)
