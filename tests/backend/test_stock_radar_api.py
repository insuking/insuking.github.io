"""P28 acceptance: /api/stock-radar/latest against the real local Postgres
(same pattern as test_dashboard_api.py) - real DB rows in, a typed
response out, an empty list on a clean slate rather than sample data.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import delete

from app.db.models import RadarScoreRow, SecurityRow
from app.db.session import session_scope
from app.main import app
from app.models.domain import Market
from app.stock_radar.persistence import persist_scan_results
from app.stock_radar.scoring import PreBreakoutScore, ScoreFactor

pytestmark = [pytest.mark.P28, pytest.mark.asyncio]

_TEST_SYMBOL_A = "TEST-API-RADAR-A"
_TEST_SYMBOL_B = "TEST-API-RADAR-B"


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(
            delete(RadarScoreRow).where(RadarScoreRow.symbol.in_([_TEST_SYMBOL_A, _TEST_SYMBOL_B]))
        )
        await session.execute(delete(SecurityRow).where(SecurityRow.symbol.in_([_TEST_SYMBOL_A, _TEST_SYMBOL_B])))
        await session.commit()


async def test_returns_the_most_recent_scans_candidates_ranked() -> None:
    results = [
        PreBreakoutScore(
            symbol=_TEST_SYMBOL_A,
            total_score=50.0,
            max_available=77.0,
            reference_close=70000.0,
            positive=[ScoreFactor("box_compression", 10.0, "변동폭이 최근 구간 중 상위 90%로 압축")],
        ),
        PreBreakoutScore(symbol=_TEST_SYMBOL_B, total_score=30.0, max_available=65.0, reference_close=80000.0),
    ]
    names = {_TEST_SYMBOL_A: "테스트API종목A", _TEST_SYMBOL_B: "테스트API종목B"}

    async with session_scope() as session:
        run_id = await persist_scan_results(session, results, names, market=Market.KOSPI)

    async with await _client() as client:
        response = await client.get("/api/stock-radar/latest")

    assert response.status_code == 200
    body = response.json()

    # get_latest_scan() only ever returns rows from a single scan_run_id,
    # and A/B are only ever written together by the persist_scan_results()
    # call above - so both showing up here already proves this test's run
    # was the latest one, without a separate scan_run_id equality check.
    by_symbol = {c["symbol"]: c for c in body["candidates"] if c["symbol"] in (_TEST_SYMBOL_A, _TEST_SYMBOL_B)}
    assert len(by_symbol) == 2
    assert body["scan_run_id"] == run_id
    assert body["scored_at"] is not None
    assert by_symbol[_TEST_SYMBOL_A]["rank"] == 1
    assert by_symbol[_TEST_SYMBOL_A]["name"] == "테스트API종목A"
    assert by_symbol[_TEST_SYMBOL_A]["max_available"] == pytest.approx(77.0)
    assert by_symbol[_TEST_SYMBOL_A]["positive"][0]["factor"] == "box_compression"
    assert by_symbol[_TEST_SYMBOL_B]["rank"] == 2
