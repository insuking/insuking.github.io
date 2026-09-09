"""P23 acceptance: stock-radar scan results actually persist to the real
local Postgres (same pattern as test_partial_profit_service.py /
test_guardian_service.py) - `securities` upsert + `radar_scores` append,
not just the pure scoring math `test_stock_radar_scoring.py` covers.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.db.models import RadarScoreRow, SecurityRow
from app.db.session import session_scope
from app.models.domain import Market
from app.stock_radar.persistence import persist_scan_results
from app.stock_radar.scoring import PreBreakoutScore, ScoreFactor

pytestmark = [pytest.mark.P23, pytest.mark.asyncio]

_TEST_SYMBOL_A = "TEST-RADAR-PERSIST-A"
_TEST_SYMBOL_B = "TEST-RADAR-PERSIST-B"


def _score(symbol: str, total: float) -> PreBreakoutScore:
    return PreBreakoutScore(
        symbol=symbol,
        total_score=total,
        max_available=65.0,
        positive=[ScoreFactor("box_compression", 10.0, "변동폭이 최근 구간 중 상위 90%로 압축")],
        negative=[],
    )


@pytest.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(RadarScoreRow).where(RadarScoreRow.symbol.in_([_TEST_SYMBOL_A, _TEST_SYMBOL_B])))
        await session.execute(delete(SecurityRow).where(SecurityRow.symbol.in_([_TEST_SYMBOL_A, _TEST_SYMBOL_B])))
        await session.commit()


async def test_persists_a_security_row_and_a_ranked_radar_score_row_per_symbol() -> None:
    results = [_score(_TEST_SYMBOL_A, 40.0), _score(_TEST_SYMBOL_B, 20.0)]
    names = {_TEST_SYMBOL_A: "테스트종목A", _TEST_SYMBOL_B: "테스트종목B"}

    async with session_scope() as session:
        run_id = await persist_scan_results(session, results, names, market=Market.KOSPI)

        security_a = await session.get(SecurityRow, _TEST_SYMBOL_A)
        assert security_a is not None
        assert security_a.name == "테스트종목A"
        assert security_a.market == "KOSPI"

        scores = (
            await session.execute(select(RadarScoreRow).where(RadarScoreRow.scan_run_id == run_id))
        ).scalars().all()
        by_symbol = {s.symbol: s for s in scores}
        assert len(scores) == 2
        assert by_symbol[_TEST_SYMBOL_A].rank == 1
        assert by_symbol[_TEST_SYMBOL_B].rank == 2
        assert by_symbol[_TEST_SYMBOL_A].prebreakout_score == pytest.approx(40.0)
        assert "box_compression" in by_symbol[_TEST_SYMBOL_A].explanation


async def test_a_second_scan_run_updates_the_security_name_without_duplicating_it() -> None:
    async with session_scope() as session:
        await persist_scan_results(
            session, [_score(_TEST_SYMBOL_A, 30.0)], {_TEST_SYMBOL_A: "옛날이름"}, market=Market.KOSPI
        )
        run_id_2 = await persist_scan_results(
            session, [_score(_TEST_SYMBOL_A, 35.0)], {_TEST_SYMBOL_A: "새이름"}, market=Market.KOSPI
        )

        security = await session.get(SecurityRow, _TEST_SYMBOL_A)
        assert security is not None
        assert security.name == "새이름"

        all_scores = (
            await session.execute(select(RadarScoreRow).where(RadarScoreRow.symbol == _TEST_SYMBOL_A))
        ).scalars().all()
        # two separate scan runs, each append-only - never overwritten in place.
        assert len(all_scores) == 2
        assert any(s.scan_run_id == run_id_2 for s in all_scores)


async def test_generates_a_scan_run_id_when_none_is_supplied() -> None:
    async with session_scope() as session:
        run_id = await persist_scan_results(session, [_score(_TEST_SYMBOL_A, 10.0)], {})

        assert run_id
        score = (
            await session.execute(select(RadarScoreRow).where(RadarScoreRow.symbol == _TEST_SYMBOL_A))
        ).scalar_one()
        assert score.scan_run_id == run_id
        assert score.scored_at.tzinfo is not None
