"""App PIN verification (P13).

One global PIN for this single-user personal-trading app - see
docs/MASTER_SPEC.md section C: "an app PIN or passkey/WebAuthn re-check
before approval is accepted". This module implements the PIN half of that
requirement.

Passkey/WebAuthn is **not implemented**: a real WebAuthn ceremony needs
browser credential registration/assertion UI and a relying-party challenge
protocol this phase doesn't build, and faking that would violate this
project's "never mark untested functionality as complete" rule. There is no
`verify_passkey()` here - approval always goes through the PIN path. This
gap is called out again in docs/ so it isn't mistaken for a finished
passkey feature later.

The PIN itself is never stored in plaintext: `APP_PIN_HASH` holds
`"<salt_hex>$<pbkdf2_hmac_sha256_hex>"`, produced once by `hash_pin()`.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from app.approval.errors import PinIncorrectError, PinNotConfiguredError
from app.core.config import Settings, get_settings

_ITERATIONS = 200_000
_ALGORITHM = "sha256"


def hash_pin(pin: str, salt: bytes | None = None) -> str:
    """Produces the `APP_PIN_HASH` value for a given PIN. `salt` is only a
    parameter so tests can make this deterministic; real callers should
    omit it and let a fresh random salt be generated."""
    salt = salt if salt is not None else os.urandom(16)
    digest = hashlib.pbkdf2_hmac(_ALGORITHM, pin.encode(), salt, _ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_pin(pin: str, settings: Settings | None = None) -> None:
    """Raises `PinNotConfiguredError` or `PinIncorrectError` on failure;
    returns normally (no return value) when `pin` matches."""
    settings = settings or get_settings()
    if not settings.app_pin_hash:
        raise PinNotConfiguredError("APP_PIN_HASH is not set - see docs/MASTER_SPEC.md section C")

    try:
        salt_hex, expected_hex = settings.app_pin_hash.split("$", 1)
        salt = bytes.fromhex(salt_hex)
    except ValueError as exc:
        raise PinNotConfiguredError("APP_PIN_HASH is malformed - expected '<salt_hex>$<hash_hex>'") from exc

    candidate = hashlib.pbkdf2_hmac(_ALGORITHM, pin.encode(), salt, _ITERATIONS)
    if not hmac.compare_digest(candidate.hex(), expected_hex):
        raise PinIncorrectError("Incorrect PIN")
