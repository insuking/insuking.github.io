"""P19 acceptance: service_restart.py against real local Postgres/Redis for
the DB/Redis reconnection helpers, and stub callables for the generic
stop-then-start `restart_service` wrapper.
"""

import pytest

from app.supervisor.service_restart import (
    restart_database_connection,
    restart_redis_connection,
    restart_service,
)

pytestmark = [pytest.mark.P19, pytest.mark.asyncio]


async def test_restart_database_connection_reconnects_real_db() -> None:
    assert await restart_database_connection() is True


async def test_restart_redis_connection_reconnects_real_redis() -> None:
    assert await restart_redis_connection() is True


async def test_restart_service_returns_true_when_both_stop_and_start_succeed() -> None:
    calls: list[str] = []

    async def stop() -> None:
        calls.append("stop")

    async def start() -> None:
        calls.append("start")

    assert await restart_service(stop, start) is True
    assert calls == ["stop", "start"]


async def test_restart_service_tolerates_a_failing_stop() -> None:
    calls: list[str] = []

    async def stop() -> None:
        raise RuntimeError("already dead")

    async def start() -> None:
        calls.append("start")

    assert await restart_service(stop, start) is True
    assert calls == ["start"]


async def test_restart_service_returns_false_when_start_fails() -> None:
    async def stop() -> None:
        return None

    async def start() -> None:
        raise RuntimeError("port already in use")

    assert await restart_service(stop, start) is False
