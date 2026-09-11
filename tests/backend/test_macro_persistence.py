"""P38: macro_persistence.py against the real local Postgres (same
pattern as test_decision_persistence.py)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.models import MacroSnapshotRow
from app.db.session import session_scope
from app.radar.macro_persistence import get_latest_macro_snapshot, persist_macro_snapshot
from app.radar.macro_regime import MacroReading, MacroRegime

pytestmark = [pytest.mark.P38, pytest.mark.asyncio]

_TEST_HEADLINE_PREFIX = "TEST-macro-"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(
            delete(MacroSnapshotRow).where(MacroSnapshotRow.headline.like(f"{_TEST_HEADLINE_PREFIX}%"))
        )
        await session.commit()


async def test_persist_and_read_back_a_risk_off_snapshot() -> None:
    reading = MacroReading(
        sp500_change_pct=-2.0, sox_change_pct=-3.0, vix_level=28.0,
        oil_change_pct=1.0, usdkrw_change_pct=0.5,
    )
    observed_at = datetime(2026, 9, 10, 8, 20, tzinfo=UTC)
    headline = f"{_TEST_HEADLINE_PREFIX}VIX 28.0 (공포 구간)"

    async with session_scope() as session:
        await persist_macro_snapshot(
            session, reading, regime=MacroRegime.RISK_OFF, headline=headline, observed_at=observed_at
        )
        await session.commit()

        latest = await get_latest_macro_snapshot(session)

    assert latest is not None
    assert latest.regime == "RISK_OFF"
    assert latest.vix_level == 28.0
    assert latest.sp500_change_pct == -2.0
    assert latest.headline == headline


async def test_persist_keeps_none_for_metrics_that_failed_to_fetch() -> None:
    reading = MacroReading(
        sp500_change_pct=None, sox_change_pct=None, vix_level=14.0,
        oil_change_pct=None, usdkrw_change_pct=None,
    )
    observed_at = datetime(2026, 9, 10, 8, 20, tzinfo=UTC)

    async with session_scope() as session:
        await persist_macro_snapshot(
            session, reading, regime=MacroRegime.NEUTRAL,
            headline=f"{_TEST_HEADLINE_PREFIX}partial", observed_at=observed_at,
        )
        await session.commit()

        latest = await get_latest_macro_snapshot(session)

    assert latest is not None
    assert latest.vix_level == 14.0
    assert latest.sp500_change_pct is None
    assert latest.sox_change_pct is None
    assert latest.oil_change_pct is None
    assert latest.usdkrw_change_pct is None


async def test_get_latest_macro_snapshot_returns_the_most_recently_observed_row() -> None:
    older = datetime(2026, 9, 9, 8, 20, tzinfo=UTC)
    newer = datetime(2026, 9, 10, 8, 20, tzinfo=UTC)
    reading = MacroReading(
        sp500_change_pct=0.1, sox_change_pct=0.1, vix_level=15.0,
        oil_change_pct=0.1, usdkrw_change_pct=0.1,
    )

    async with session_scope() as session:
        await persist_macro_snapshot(
            session, reading, regime=MacroRegime.NEUTRAL,
            headline=f"{_TEST_HEADLINE_PREFIX}older", observed_at=older,
        )
        await persist_macro_snapshot(
            session, reading, regime=MacroRegime.RISK_ON,
            headline=f"{_TEST_HEADLINE_PREFIX}newer", observed_at=newer,
        )
        await session.commit()

        latest = await get_latest_macro_snapshot(session)

    assert latest is not None
    assert latest.observed_at == newer
    assert latest.headline == f"{_TEST_HEADLINE_PREFIX}newer"
