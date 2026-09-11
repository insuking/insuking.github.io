"""P38: persist/read the daily premarket macro snapshot
(`app/radar/macro_regime.py`) so the 시장 탭's "해외 매크로" card can show
the most recent reading."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MacroSnapshotRow
from app.radar.macro_regime import MacroReading, MacroRegime


async def persist_macro_snapshot(
    session: AsyncSession,
    reading: MacroReading,
    regime: MacroRegime,
    headline: str,
    observed_at: datetime,
) -> None:
    """Does not commit - the caller controls the transaction boundary,
    matching `app.radar.candle_persistence.persist_candles()`."""
    session.add(
        MacroSnapshotRow(
            observed_at=observed_at,
            sp500_change_pct=reading.sp500_change_pct,
            sox_change_pct=reading.sox_change_pct,
            vix_level=reading.vix_level,
            oil_change_pct=reading.oil_change_pct,
            usdkrw_change_pct=reading.usdkrw_change_pct,
            regime=regime.value,
            headline=headline,
            created_at=observed_at,
        )
    )


async def get_latest_macro_snapshot(session: AsyncSession) -> MacroSnapshotRow | None:
    result = await session.execute(
        select(MacroSnapshotRow).order_by(MacroSnapshotRow.observed_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()
