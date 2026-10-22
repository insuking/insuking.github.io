"""P19 acceptance: the classification is exhaustive and disjoint over every
`FailureType` member, and every listed type lands in exactly the auto-
recoverable/never-auto-resolved bucket docs/MASTER_SPEC.md section L-R
specifies.
"""

import pytest

from app.supervisor.failure_classifier import (
    AUTO_RECOVERABLE,
    NEVER_AUTO_RESOLVED,
    FailureType,
    is_auto_recoverable,
    requires_human_action,
)

pytestmark = pytest.mark.P19


def test_auto_recoverable_and_never_auto_resolved_are_disjoint() -> None:
    assert AUTO_RECOVERABLE & NEVER_AUTO_RESOLVED == frozenset()


def test_auto_recoverable_and_never_auto_resolved_are_exhaustive() -> None:
    assert AUTO_RECOVERABLE | NEVER_AUTO_RESOLVED == frozenset(FailureType)


@pytest.mark.parametrize(
    "failure_type",
    [
        FailureType.WEBSOCKET_DISCONNECT,
        FailureType.TRANSIENT_REDIS_FAILURE,
        FailureType.DB_CONNECTION_RESET,
        FailureType.API_TIMEOUT,
        FailureType.TEMPORARY_DNS_FAILURE,
        FailureType.PROCESS_CRASH,
        FailureType.STALE_CACHE,
        FailureType.EXPIRED_ACCESS_TOKEN,
        FailureType.CONSUMER_LAG,
        FailureType.FRONTEND_API_RETRY,
        FailureType.TEMPORARY_NOTIFICATION_FAILURE,
    ],
)
def test_auto_recoverable_types(failure_type: FailureType) -> None:
    assert is_auto_recoverable(failure_type) is True
    assert requires_human_action(failure_type) is False


@pytest.mark.parametrize(
    "failure_type",
    [
        FailureType.UNKNOWN_ORDER_STATUS,
        FailureType.POSITION_MISMATCH,
        FailureType.UNEXPECTED_BROKER_HOLDINGS,
        FailureType.UNKNOWN_FILL_QUANTITY,
        FailureType.DUPLICATE_ORDER_AMBIGUITY,
        FailureType.ACCOUNT_AUTHORIZATION_ERROR,
        FailureType.MANUAL_ORDER_CONFLICT,
        FailureType.UNEXPECTED_ASSET_BALANCE,
    ],
)
def test_never_auto_resolved_types(failure_type: FailureType) -> None:
    assert is_auto_recoverable(failure_type) is False
    assert requires_human_action(failure_type) is True
