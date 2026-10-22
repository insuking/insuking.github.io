"""Approval token security (P13).

See docs/MASTER_SPEC.md section D: single-use, short TTL (120-300s, see
Settings.approval_token_ttl_seconds), server-stored hash - never the
plaintext - bound to recommendation_id + user_id (enforced by
app/approval/service.py, which stores both on the `Approval` row itself),
consumed on use, reuse returns HTTP 410 (see app/api/approvals.py).

The token carries 256 bits of entropy from `secrets.token_urlsafe`, so a
plain deterministic SHA-256 hash is looked up directly by equality (no
per-token salt, unlike password hashing) - the same approach used for
high-entropy API/session tokens generally; salting only matters when the
thing being hashed is low-entropy enough to brute-force.
"""

from __future__ import annotations

import hashlib
import secrets

_TOKEN_BYTES = 32


def generate_token() -> tuple[str, str]:
    """Returns `(plaintext, sha256_hex_hash)`. Only the hash is ever stored;
    the plaintext is handed to the caller once, to embed in the approval
    link, and never persisted."""
    plaintext = secrets.token_urlsafe(_TOKEN_BYTES)
    return plaintext, hash_token(plaintext)


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()
