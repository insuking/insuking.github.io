"""P37: persist real benchmark candles so the dashboard's market-regime
read (`app/api/dashboard.py`'s `_latest_regime()`) has real data to read.

**The gap this closes**: `_latest_regime()` reads the generic `candles`
table (`CandleRow`), but nothing in production ever wrote to it - the
KOSPI benchmark `scripts/scan_stocks.py` fetches every run, and the BTC
benchmark `scripts/scan_crypto.py` fetches every run, were both used
in-memory for that script's own regime read and then discarded. The 시장
(Market) tab's "국내 시장: 데이터 없음" was never a display bug - the
candles it needed to classify a regime from were never persisted
anywhere. (`scripts/seed_demo_data.py`'s KRW-BTC candles are dev/demo
data only, and age out of the 20-day moving-average window over time
regardless - not a fix for a real deployment.)

Delete-then-insert per symbol over the exact date range being written,
matching the idempotent-replace convention `scan_crypto.py`/
`reconfirm_entries.py` already use for `Recommendation` rows - a re-run
over overlapping history replaces rather than duplicates.
"""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Candle as CandleRow
from app.models.domain import Candle


async def persist_candles(session: AsyncSession, candles: list[Candle]) -> None:
    """Does not commit - same convention as `app.stock_radar.
    regime_persistence`'s persist functions, so a caller can batch this
    with other writes in one transaction. No-ops on an empty list rather
    than issuing a pointless delete."""
    if not candles:
        return
    symbol = candles[0].symbol
    interval = candles[0].interval
    start = min(c.open_time for c in candles)
    end = max(c.open_time for c in candles)

    await session.execute(
        delete(CandleRow).where(
            CandleRow.symbol == symbol,
            CandleRow.interval == interval,
            CandleRow.open_time >= start,
            CandleRow.open_time <= end,
        )
    )
    for c in candles:
        session.add(
            CandleRow(
                symbol=c.symbol,
                interval=c.interval,
                open=c.open,
                high=c.high,
                low=c.low,
                close=c.close,
                volume=c.volume,
                open_time=c.open_time,
                close_time=c.close_time,
            )
        )
