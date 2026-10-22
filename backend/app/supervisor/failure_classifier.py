"""Failure classification (P19 CLASSIFY step).

Per docs/MASTER_SPEC.md section L-R, every detected failure is either
**auto-recoverable** (self-healing may act) or **never auto-resolved**
(blocks new trades, raises a P1 alert, requires manual review) - two fixed,
enumerated lists copied verbatim from the master spec, not a judgment call
this module invents. The two sets are exhaustive and disjoint by
construction: every `FailureType` member belongs to exactly one (see
tests/backend/test_supervisor_failure_classifier.py's invariant check).
"""

from __future__ import annotations

from enum import Enum


class FailureType(str, Enum):
    # Auto-recoverable
    WEBSOCKET_DISCONNECT = "WEBSOCKET_DISCONNECT"
    TRANSIENT_REDIS_FAILURE = "TRANSIENT_REDIS_FAILURE"
    DB_CONNECTION_RESET = "DB_CONNECTION_RESET"
    API_TIMEOUT = "API_TIMEOUT"
    TEMPORARY_DNS_FAILURE = "TEMPORARY_DNS_FAILURE"
    PROCESS_CRASH = "PROCESS_CRASH"
    STALE_CACHE = "STALE_CACHE"
    EXPIRED_ACCESS_TOKEN = "EXPIRED_ACCESS_TOKEN"
    CONSUMER_LAG = "CONSUMER_LAG"
    FRONTEND_API_RETRY = "FRONTEND_API_RETRY"
    TEMPORARY_NOTIFICATION_FAILURE = "TEMPORARY_NOTIFICATION_FAILURE"

    # Never auto-resolved
    UNKNOWN_ORDER_STATUS = "UNKNOWN_ORDER_STATUS"
    POSITION_MISMATCH = "POSITION_MISMATCH"
    UNEXPECTED_BROKER_HOLDINGS = "UNEXPECTED_BROKER_HOLDINGS"
    UNKNOWN_FILL_QUANTITY = "UNKNOWN_FILL_QUANTITY"
    DUPLICATE_ORDER_AMBIGUITY = "DUPLICATE_ORDER_AMBIGUITY"
    ACCOUNT_AUTHORIZATION_ERROR = "ACCOUNT_AUTHORIZATION_ERROR"
    MANUAL_ORDER_CONFLICT = "MANUAL_ORDER_CONFLICT"
    UNEXPECTED_ASSET_BALANCE = "UNEXPECTED_ASSET_BALANCE"


AUTO_RECOVERABLE: frozenset[FailureType] = frozenset(
    {
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
    }
)

NEVER_AUTO_RESOLVED: frozenset[FailureType] = frozenset(
    {
        FailureType.UNKNOWN_ORDER_STATUS,
        FailureType.POSITION_MISMATCH,
        FailureType.UNEXPECTED_BROKER_HOLDINGS,
        FailureType.UNKNOWN_FILL_QUANTITY,
        FailureType.DUPLICATE_ORDER_AMBIGUITY,
        FailureType.ACCOUNT_AUTHORIZATION_ERROR,
        FailureType.MANUAL_ORDER_CONFLICT,
        FailureType.UNEXPECTED_ASSET_BALANCE,
    }
)


def is_auto_recoverable(failure_type: FailureType) -> bool:
    return failure_type in AUTO_RECOVERABLE


def requires_human_action(failure_type: FailureType) -> bool:
    return failure_type in NEVER_AUTO_RESOLVED
