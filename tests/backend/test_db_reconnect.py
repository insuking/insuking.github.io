"""P2 acceptance: 'DB restart recovery'.

Actually restarts the local Postgres service and proves the app's engine
(pool_pre_ping=True, see app/db/session.py) recovers on its own without
recreating the engine object - the same resilience path relied on when the
docker-compose `postgres` container restarts. Skipped when this sandbox
lacks the OS-level control to restart the service (e.g. a locked-down CI
runner or a machine where Postgres lives in a separate container reachable
only over the network) rather than faking a pass.
"""

import asyncio
import shutil
import subprocess
import time

import pytest

from app.db.session import check_database

pytestmark = [
    pytest.mark.P2,
    pytest.mark.skipif(
        shutil.which("service") is None,
        reason="no local OS service control available in this environment",
    ),
]


def _restart_postgres() -> bool:
    result = subprocess.run(
        ["service", "postgresql", "restart"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.returncode == 0


@pytest.mark.asyncio
async def test_check_database_recovers_after_service_restart() -> None:
    assert await check_database() is True

    restarted = _restart_postgres()
    if not restarted:
        pytest.skip("could not restart local postgresql service (no permission?)")

    # pool_pre_ping discards the now-stale pooled connection and opens a
    # fresh one on the next query - poll briefly for the server to accept
    # connections again rather than assuming an instant restart.
    deadline = time.monotonic() + 15
    recovered = False
    while time.monotonic() < deadline:
        if await check_database():
            recovered = True
            break
        await asyncio.sleep(0.5)

    assert recovered, "check_database() did not recover within 15s of postgres restarting"
