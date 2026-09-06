"""Execution-provider exceptions (P15).

Shared across brokers (Toss, Upbit) - each provider module maps its own
broker-specific errors onto these where the distinction matters generically
(safety gate, timeout/idempotency), and lets broker-specific errors
(`TossApiError`, future Upbit equivalents) propagate otherwise.
"""


class ExecutionError(Exception):
    """Base class for execution-provider errors."""


class LiveTradingDisabledError(ExecutionError):
    """Refused to place/modify/cancel a real order because `LIVE_TRADING`
    is not enabled (docs/MASTER_SPEC.md section A: absolute safety rule).
    Raised before any network call is made - a broker credential being
    configured is never, by itself, enough to place a real order.
    """


class OrderTimeoutError(ExecutionError):
    """No confirmed response was received for an order request (network
    timeout, or a broker-reported duplicate whose original outcome isn't
    retrievable) within the outcome this module could confirm.

    Per docs/MASTER_SPEC.md P15 ("no blind retries"), callers must not
    resubmit automatically - call the provider's `reconcile_order()` to
    find out what actually happened before deciding what to do next. The
    local order this refers to is left in `UNKNOWN` status, never silently
    assumed to have succeeded or failed.
    """

    def __init__(self, message: str, *, client_order_id: str) -> None:
        self.client_order_id = client_order_id
        super().__init__(message)
