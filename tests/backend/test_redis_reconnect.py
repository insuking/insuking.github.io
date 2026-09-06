"""P2 acceptance: 'Redis restart recovery'.

Actually kills and restarts the local `redis-server` process and proves the
app's cached client (app/db/redis_client.py) recovers on its own without
being recreated - redis-py opens a fresh socket on the next command after a
connection error. Skipped when this sandbox has no `redis-server` binary to
restart, rather than faking a pass.
"""

import asyncio
import shutil
import subprocess
import time

import pytest

from app.db.redis_client import check_redis

pytestmark = [
    pytest.mark.P2,
    pytest.mark.skipif(
        shutil.which("redis-server") is None or shutil.which("pkill") is None,
        reason="no local redis-server / pkill available in this environment",
    ),
]


def _restart_redis() -> None:
    subprocess.run(["pkill", "-f", "redis-server.*:6379"], capture_output=True, check=False)
    time.sleep(0.5)
    subprocess.run(
        ["redis-server", "--daemonize", "yes", "--port", "6379"],
        capture_output=True,
        check=True,
    )


@pytest.mark.asyncio
async def test_check_redis_recovers_after_process_restart() -> None:
    assert await check_redis() is True

    _restart_redis()

    deadline = time.monotonic() + 10
    recovered = False
    while time.monotonic() < deadline:
        if await check_redis():
            recovered = True
            break
        await asyncio.sleep(0.3)

    assert recovered, "check_redis() did not recover within 10s of redis-server restarting"
