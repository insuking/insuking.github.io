"""P45: persist/read `AccountBalanceSnapshotRow` - real periodic combined-
balance readings backing the home screen's "자산 추이" (asset trend)
chart. Append-only, same convention as `app/radar/macro_persistence.py`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.account.balance import CombinedBalance
from app.db.models import AccountBalanceSnapshotRow


async def persist_balance_snapshot(
    session: AsyncSession, balance: CombinedBalance, as_of: datetime
) -> AccountBalanceSnapshotRow:
    """Does not commit - the caller controls the transaction boundary,
    matching `app.radar.candle_persistence.persist_candles()`."""
    row = AccountBalanceSnapshotRow(
        as_of=as_of,
        kis_total_value=balance.kis_total_value,
        upbit_total_value=balance.upbit_total_value,
        total_assets=balance.total_assets,
        created_at=as_of,
    )
    session.add(row)
    return row


async def get_balance_history(
    session: AsyncSession, since: datetime, limit: int = 2000
) -> list[AccountBalanceSnapshotRow]:
    """Chronological (oldest first, matching every other real time-series
    read in this project) real snapshots since `since` - an empty list on
    a fresh deployment, or before `scripts/snapshot_balance.py` has run
    even once, is the honest answer, not a fabricated curve."""
    result = await session.execute(
        select(AccountBalanceSnapshotRow)
        .where(AccountBalanceSnapshotRow.as_of >= since)
        .order_by(AccountBalanceSnapshotRow.as_of.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_latest_balance_snapshot(session: AsyncSession) -> AccountBalanceSnapshotRow | None:
    result = await session.execute(
        select(AccountBalanceSnapshotRow).order_by(AccountBalanceSnapshotRow.as_of.desc()).limit(1)
    )
    return result.scalar_one_or_none()
