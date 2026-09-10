"""P34/P35 acceptance: regime_persistence.py against the real local
Postgres (same pattern as test_stock_radar_persistence.py)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.db.models import OverheatScoreRow, RegimeRelativeStrengthRow
from app.db.session import session_scope
from app.stock_radar.overheat import HeatScore, HeatStatus
from app.stock_radar.regime_interaction import InteractionLabel, InteractionScore
from app.stock_radar.regime_persistence import persist_interaction_score, upsert_heat_score

pytestmark = [pytest.mark.P34, pytest.mark.P35, pytest.mark.asyncio]

_TEST_SYMBOL = "TEST-REGIME-PERSIST-A"


@pytest.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(RegimeRelativeStrengthRow).where(RegimeRelativeStrengthRow.symbol == _TEST_SYMBOL))
        await session.execute(delete(OverheatScoreRow).where(OverheatScoreRow.symbol == _TEST_SYMBOL))
        await session.commit()


async def test_persist_interaction_score_writes_a_readable_row() -> None:
    score = InteractionScore(
        weak_market_resilience_score=2.0,
        flow_resilience_score=2.0,
        interaction_score=4.0,
        label=InteractionLabel.STRONG_RELATIVE_STRENGTH,
    )
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)

    async with session_scope() as session:
        await persist_interaction_score(
            session,
            symbol=_TEST_SYMBOL,
            market_regime="RISK_OFF",
            benchmark_return_pct=-2.0,
            stock_return_pct=1.5,
            foreign_net_today=500.0,
            institution_net_today=300.0,
            score=score,
            observed_at=observed_at,
        )
        await session.commit()

        row = (
            await session.execute(
                select(RegimeRelativeStrengthRow).where(RegimeRelativeStrengthRow.symbol == _TEST_SYMBOL)
            )
        ).scalar_one()

    assert row.interaction_score == pytest.approx(4.0)
    assert row.label == "STRONG_RELATIVE_STRENGTH"
    assert row.market_regime == "RISK_OFF"
    assert row.observed_at == observed_at


async def test_persist_interaction_score_appends_rather_than_overwrites() -> None:
    score = InteractionScore(0.0, 0.0, 0.0, InteractionLabel.NEUTRAL)
    async with session_scope() as session:
        await persist_interaction_score(
            session, symbol=_TEST_SYMBOL, market_regime="NEUTRAL", benchmark_return_pct=0.0,
            stock_return_pct=0.0, foreign_net_today=0.0, institution_net_today=0.0, score=score,
        )
        await persist_interaction_score(
            session, symbol=_TEST_SYMBOL, market_regime="NEUTRAL", benchmark_return_pct=0.0,
            stock_return_pct=0.0, foreign_net_today=0.0, institution_net_today=0.0, score=score,
        )
        await session.commit()

        rows = (
            await session.execute(
                select(RegimeRelativeStrengthRow).where(RegimeRelativeStrengthRow.symbol == _TEST_SYMBOL)
            )
        ).scalars().all()

    assert len(rows) == 2


async def test_upsert_heat_score_writes_a_readable_row() -> None:
    score = HeatScore(
        return_1d_pct=8.5, return_2d_pct=9.0, return_5d_pct=10.0, distance_from_signal_pct=None,
        gap_pct=None, volume_ratio=1.5, atr_extension=None, heat_score=106.25, status=HeatStatus.TOO_LATE,
    )
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)

    async with session_scope() as session:
        await upsert_heat_score(session, symbol=_TEST_SYMBOL, score=score, observed_at=observed_at)
        await session.commit()

        row = await session.get(OverheatScoreRow, (_TEST_SYMBOL, observed_at))

    assert row is not None
    assert row.status == "TOO_LATE"
    assert row.heat_score == pytest.approx(106.25)


async def test_upsert_heat_score_replaces_rather_than_duplicates_the_same_observation() -> None:
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)
    first = HeatScore(1.0, 1.0, 1.0, None, None, 1.0, None, 10.0, HeatStatus.NORMAL)
    second = HeatScore(9.0, 9.0, 9.0, None, None, 1.0, None, 112.5, HeatStatus.TOO_LATE)

    async with session_scope() as session:
        await upsert_heat_score(session, symbol=_TEST_SYMBOL, score=first, observed_at=observed_at)
        await session.commit()

    async with session_scope() as session:
        await upsert_heat_score(session, symbol=_TEST_SYMBOL, score=second, observed_at=observed_at)
        await session.commit()

        rows = (
            await session.execute(select(OverheatScoreRow).where(OverheatScoreRow.symbol == _TEST_SYMBOL))
        ).scalars().all()

    assert len(rows) == 1
    assert rows[0].status == "TOO_LATE"
    assert rows[0].heat_score == pytest.approx(112.5)
