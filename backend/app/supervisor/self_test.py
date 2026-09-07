"""Post-recovery verification (P19 VERIFY step).

A recovery action is not "done" just because it didn't raise -
`verify_recovery` re-runs the same probe that detected the failure a
bounded number of times to confirm the fix actually took, before
`recovery_manager.py` decides RESUME vs REMAIN PAUSED (docs/MASTER_SPEC.md
section L-R's flow: "...RECOVER -> VERIFY -> RESUME OR REMAIN PAUSED").
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

DEFAULT_VERIFY_ATTEMPTS = 3


async def verify_recovery(
    probe: Callable[[], Awaitable[bool]],
    attempts: int = DEFAULT_VERIFY_ATTEMPTS,
    delay_seconds: float = 0.0,
) -> bool:
    for attempt in range(attempts):
        if await probe():
            return True
        if attempt < attempts - 1 and delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
    return False
