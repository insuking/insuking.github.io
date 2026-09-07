"""Rate limiting (P21) for the approval decide endpoint.

`ApprovalService.decide()` deliberately leaves an approval open (not
terminal) after a wrong PIN (see `app/approval/service.py`'s `PIN re-check`
comment) - retrying with the correct PIN is the whole point of a re-check.
That also means nothing else in this codebase bounds how many PIN guesses a
holder of one approval link can make before it expires
(`approval_token_ttl_seconds`, 120-300s) - a 4-6 digit PIN is well within
brute-force range over even a 300s window without a limit. Scoped per
*token* rather than per-user: the actual attack surface is unlimited
guesses against one stolen/guessed approval link, not a user's overall
request volume.

A fixed window rather than a sliding one - simpler, and "at most
N attempts, then wait out the rest of the window" is an acceptable, easily
explained bound for a PIN re-check that a legitimate user only ever needs
once.
"""

from __future__ import annotations

from redis.asyncio import Redis

_KEY_PREFIX = "approval_decide_rate_limit:"


async def check_and_record_attempt(
    redis: Redis, token: str, *, max_attempts: int, window_seconds: int
) -> bool:
    """Records one attempt against `token`'s window and returns whether it
    is allowed (`True`) or the window's attempt budget is exhausted
    (`False`). Always records, even when denied, so a caller who ignores a
    denial doesn't get extra budget."""
    key = f"{_KEY_PREFIX}{token}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    return count <= max_attempts
