"""Shared test fixtures.

app.db.session and app.db.redis_client cache a single engine/client for the
life of the process (correct for a long-running server bound to one event
loop). pytest-asyncio gives each test function its own event loop, so a
connection object created in test A's loop is invalid in test B's - this
fixture resets both singletons before every test so each one starts clean
and reconnects on its own loop instead of raising
"Future attached to a different loop".
"""

import pytest_asyncio

from app.db.redis_client import close_redis
from app.db.session import dispose_engine


@pytest_asyncio.fixture(autouse=True)
async def _reset_connection_singletons():
    await dispose_engine()
    await close_redis()
    yield
    await dispose_engine()
    await close_redis()
