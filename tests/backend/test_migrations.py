"""P2 acceptance: 'migration up/down' against a real Postgres instance.

No mocking - this drives the actual `alembic` command against DATABASE_URL,
per the master spec's rule that integration tests must not fake the thing
they claim to verify.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

pytestmark = pytest.mark.P2

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"

EXPECTED_TABLES = {
    "market_ticks",
    "candles",
    "features",
    "signals",
    "recommendations",
    "approvals",
    "trade_plans",
    "orders",
    "fills",
    "positions",
    "protective_orders",
    "system_health",
    "incidents",
    "audit_logs",
    "performance",
}


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def _current_tables() -> set[str]:
    async def _list_tables() -> set[str]:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.connect() as conn:
                names = await conn.run_sync(lambda c: sa.inspect(c).get_table_names())
                return set(names)
        finally:
            await engine.dispose()

    return asyncio.run(_list_tables())


def test_upgrade_head_creates_every_p2_table() -> None:
    result = _run_alembic("upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr

    tables = _current_tables()
    missing = EXPECTED_TABLES - tables
    assert not missing, f"migration did not create: {missing}"


def test_downgrade_base_removes_every_p2_table() -> None:
    _run_alembic("upgrade", "head")
    result = _run_alembic("downgrade", "base")
    assert result.returncode == 0, result.stdout + result.stderr

    tables = _current_tables()
    leftover = EXPECTED_TABLES & tables
    assert not leftover, f"still present after downgrade: {leftover}"

    # Leave the database in the normal, migrated state for every other test.
    upgrade_again = _run_alembic("upgrade", "head")
    assert upgrade_again.returncode == 0, upgrade_again.stdout + upgrade_again.stderr
