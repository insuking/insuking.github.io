"""Service restart (P19 RECOVER step for infrastructure failures).

Only ever wraps recovery actions docs/MASTER_SPEC.md's auto-recoverable
list actually covers (WebSocket disconnect, transient Redis failure, DB
connection reset, process crash) - reusing what each integration already
built for itself rather than reimplementing reconnect logic:

- Database: P2's `pool_pre_ping`-backed engine already recovers a stale
  pooled connection on the next query (see test_db_reconnect.py) -
  `restart_database_connection()` just forces a fresh engine and confirms
  it can connect, for the cases where the pool itself is wedged.
- Redis: same idea via `app.db.redis_client`.
- WebSocket clients (P3/P7's `KisWebSocketClient`/`UpbitWebSocketClient`)
  already reconnect *inside* their own `run()` loop - this module doesn't
  reimplement that. `restart_service()` is a generic stop-then-start
  wrapper for when the surrounding task itself needs restarting (e.g. a
  `PROCESS_CRASH`), not a replacement for socket-level reconnect.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.db.redis_client import check_redis, close_redis
from app.db.session import check_database, dispose_engine

log = logging.getLogger(__name__)


async def restart_database_connection() -> bool:
    await dispose_engine()
    return await check_database()


async def restart_redis_connection() -> bool:
    await close_redis()
    return await check_redis()


async def restart_service(
    stop: Callable[[], Awaitable[None]], start: Callable[[], Awaitable[None]]
) -> bool:
    """Stops then starts a service. `stop` failing is tolerated (a crashed
    service is often already effectively stopped) - only `start` failing
    is reported as an unsuccessful restart."""
    try:
        await stop()
    except Exception:
        # A failing stop() must not block the restart attempt.
        log.warning("service_restart: stop() failed, proceeding to start() anyway", exc_info=True)

    try:
        await start()
    except Exception:  # noqa: BLE001 - restart failure is reported, not raised
        return False
    return True
