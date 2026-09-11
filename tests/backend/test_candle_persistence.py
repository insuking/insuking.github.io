"""P37 acceptance: candle_persistence.py against the real local Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.models import Candle as CandleRow
from app.db.session import session_scope
from app.models.domain import Candle
from app.radar.candle_persistence import persist_candles

pytestmark = [pytest.mark.P37, pytest.mark.asyncio]

_TEST_SYMBOL = "TEST-CANDLE-PERSIST"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(CandleRow).where(CandleRow.symbol == _TEST_SYMBOL))
        await session.commit()


def _candle(close: float, day: int) -> Candle:
    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return Candle(
        symbol=_TEST_SYMBOL,
        interval="1d",
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000,
        open_time=start,
        close_time=start + timedelta(days=1),
    )


async def test_persist_candles_writes_readable_rows() -> None:
    candles = [_candle(100.0 + i, day=i) for i in range(5)]

    async with session_scope() as session:
        await persist_candles(session, candles)
        await session.commit()

        rows = (
            await session.execute(select(CandleRow).where(CandleRow.symbol == _TEST_SYMBOL))
        ).scalars().all()

    assert len(rows) == 5
    assert {r.close for r in rows} == {100.0, 101.0, 102.0, 103.0, 104.0}


async def test_persist_candles_on_empty_list_is_a_noop() -> None:
    async with session_scope() as session:
        await persist_candles(session, [])
        await session.commit()

        rows = (
            await session.execute(select(CandleRow).where(CandleRow.symbol == _TEST_SYMBOL))
        ).scalars().all()

    assert rows == []


async def test_persist_candles_replaces_overlapping_history_rather_than_duplicating() -> None:
    first_run = [_candle(100.0 + i, day=i) for i in range(5)]
    second_run = [_candle(200.0 + i, day=i) for i in range(5)]  # same 5 days, different closes

    async with session_scope() as session:
        await persist_candles(session, first_run)
        await session.commit()

    async with session_scope() as session:
        await persist_candles(session, second_run)
        await session.commit()

        rows = (
            await session.execute(select(CandleRow).where(CandleRow.symbol == _TEST_SYMBOL))
        ).scalars().all()

    assert len(rows) == 5
    assert {r.close for r in rows} == {200.0, 201.0, 202.0, 203.0, 204.0}
