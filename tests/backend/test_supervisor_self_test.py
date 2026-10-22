"""P19 acceptance: self_test.py's post-recovery verification - a bounded
number of probe retries, never claiming success the probe never actually
reported.
"""

import pytest

from app.supervisor.self_test import verify_recovery

pytestmark = [pytest.mark.P19, pytest.mark.asyncio]


async def test_verify_recovery_true_when_probe_succeeds_immediately() -> None:
    async def probe() -> bool:
        return True

    assert await verify_recovery(probe) is True


async def test_verify_recovery_false_when_probe_never_succeeds() -> None:
    async def probe() -> bool:
        return False

    assert await verify_recovery(probe, attempts=3) is False


async def test_verify_recovery_succeeds_on_a_later_attempt() -> None:
    calls = {"count": 0}

    async def probe() -> bool:
        calls["count"] += 1
        return calls["count"] >= 3

    assert await verify_recovery(probe, attempts=5) is True
    assert calls["count"] == 3


async def test_verify_recovery_calls_probe_exactly_attempts_times_when_never_true() -> None:
    calls = {"count": 0}

    async def probe() -> bool:
        calls["count"] += 1
        return False

    assert await verify_recovery(probe, attempts=4) is False
    assert calls["count"] == 4
