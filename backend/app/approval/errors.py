"""Approval flow exceptions (P13).

Kept separate from HTTP concerns - app/api/approvals.py maps each of these
to a status code. Raised by app/approval/service.py and app/approval/pin.py.
"""


class ApprovalNotFoundError(Exception):
    """No approval matches the given token, or its recommendation is gone."""


class ApprovalUserMismatchError(Exception):
    """The requesting user_id doesn't own this approval."""


class ApprovalNotAuthenticatedError(Exception):
    """No currently-valid Kakao Login session exists for this user (see
    docs/MASTER_SPEC.md section C: authenticated user + one-time token +
    PIN, all three required)."""


class ApprovalGoneError(Exception):
    """The token has already been consumed by a terminal decision, or the
    approval has expired - docs/MASTER_SPEC.md section D: reuse returns
    HTTP 410, never silently re-processed."""


class InvalidDecisionError(Exception):
    """A malformed decide() request - e.g. no override_amount for
    APPROVE_WITH_AMOUNT_CHANGE."""


class PinNotConfiguredError(Exception):
    """APP_PIN_HASH is unset or malformed - approval fails closed rather
    than silently skipping the PIN re-check the master spec requires."""


class PinIncorrectError(Exception):
    """The submitted PIN didn't match."""
