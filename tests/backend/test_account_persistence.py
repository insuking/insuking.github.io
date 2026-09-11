"""P45: app/account/persistence.py against the real local Postgres (same
pattern as test_risk_service.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.account.balance import CombinedBalance
from app.account.persistence import get_balance_history, get_latest_balance_snapshot, persist_balance_snapshot
from app.db.models import AccountBalanceSnapshotRow
from app.db.session import session_scope

pytestmark = [pytest.mark.P45, pytest.mark.asyncio]


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    cutoff = datetime.now(UTC) - timedelta(seconds=1)
    yield
    async with session_scope() as session:
        await session.execute(delete(AccountBalanceSnapshotRow).where(AccountBalanceSnapshotRow.as_of >= cutoff))
        await session.commit()


async def test_persist_and_read_back_a_snapshot() -> None:
    as_of = datetime.now(UTC)
    balance = CombinedBalance(kis_total_value=1_000_000.0, upbit_total_value=500_000.0)

    async with session_scope() as session:
        await persist_balance_snapshot(session, balance, as_of)
        await session.commit()

        latest = await get_latest_balance_snapshot(session)

    assert latest is not None
    assert latest.kis_total_value == 1_000_000.0
    assert latest.upbit_total_value == 500_000.0
    assert latest.total_assets == 1_500_000.0


async def test_persist_keeps_total_assets_correct_when_one_broker_is_none() -> None:
    as_of = datetime.now(UTC)
    balance = CombinedBalance(kis_total_value=None, upbit_total_value=250_000.0)

    async with session_scope() as session:
        await persist_balance_snapshot(session, balance, as_of)
        await session.commit()

        latest = await get_latest_balance_snapshot(session)

    assert latest is not None
    assert latest.kis_total_value is None
    assert latest.total_assets == 250_000.0


async def test_get_balance_history_returns_snapshots_chronologically_since_the_given_time() -> None:
    base = datetime.now(UTC)
    older = base + timedelta(seconds=1)
    newer = base + timedelta(seconds=2)
    too_old = base - timedelta(days=1)

    async with session_scope() as session:
        await persist_balance_snapshot(session, CombinedBalance(1.0, 1.0), too_old)
        await persist_balance_snapshot(session, CombinedBalance(2.0, 2.0), older)
        await persist_balance_snapshot(session, CombinedBalance(3.0, 3.0), newer)
        await session.commit()

        history = await get_balance_history(session, since=base)

    assert [row.total_assets for row in history] == [4.0, 6.0]  # too_old excluded, oldest-first


async def test_get_latest_balance_snapshot_returns_none_when_nothing_recorded_in_range() -> None:
    async with session_scope() as session:
        history = await get_balance_history(session, since=datetime.now(UTC) + timedelta(days=365))

    assert history == []
