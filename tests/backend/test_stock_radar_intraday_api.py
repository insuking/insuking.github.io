"""P41 acceptance: /api/stock-radar/{symbol}/intraday against the real
local Postgres (same pattern as test_stock_radar_api.py)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.models import OverheatScoreRow, RegimeRelativeStrengthRow
from app.db.session import session_scope
from app.main import app
from app.stock_radar.overheat import HeatScore, HeatStatus
from app.stock_radar.regime_interaction import InteractionLabel, InteractionScore
from app.stock_radar.regime_persistence import persist_interaction_score, upsert_heat_score

pytestmark = [pytest.mark.P41, pytest.mark.asyncio]

_TEST_SYMBOL = "TEST-API-INTRADAY-A"


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(RegimeRelativeStrengthRow).where(RegimeRelativeStrengthRow.symbol == _TEST_SYMBOL))
        await session.execute(delete(OverheatScoreRow).where(OverheatScoreRow.symbol == _TEST_SYMBOL))
        await session.commit()


async def test_returns_the_days_interaction_and_heat_readings_in_order() -> None:
    older = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    newer = datetime(2026, 9, 10, 9, 30, tzinfo=UTC)
    interaction_score = InteractionScore(2.0, 0.0, 2.0, InteractionLabel.STRONG_RELATIVE_STRENGTH)
    heat_score = HeatScore(1.0, 2.0, 3.0, None, None, 1.2, None, 20.0, HeatStatus.WARM)

    async with session_scope() as session:
        await persist_interaction_score(
            session, symbol=_TEST_SYMBOL, market_regime="RISK_ON", benchmark_return_pct=-1.0,
            stock_return_pct=1.0, foreign_net_today=100.0, institution_net_today=50.0,
            score=interaction_score, observed_at=older,
        )
        await persist_interaction_score(
            session, symbol=_TEST_SYMBOL, market_regime="RISK_ON", benchmark_return_pct=-1.0,
            stock_return_pct=1.5, foreign_net_today=120.0, institution_net_today=60.0,
            score=interaction_score, observed_at=newer,
        )
        await upsert_heat_score(session, symbol=_TEST_SYMBOL, score=heat_score, observed_at=older)
        await upsert_heat_score(session, symbol=_TEST_SYMBOL, score=heat_score, observed_at=newer)
        await session.commit()

    async with await _client() as client:
        response = await client.get(
            f"/api/stock-radar/{_TEST_SYMBOL}/intraday", params={"since": "2026-09-10T00:00:00Z"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == _TEST_SYMBOL
    assert len(body["interaction_readings"]) == 2
    assert len(body["heat_readings"]) == 2
    assert body["interaction_readings"][0]["observed_at"] < body["interaction_readings"][1]["observed_at"]
    assert body["interaction_readings"][0]["label"] == "STRONG_RELATIVE_STRENGTH"
    assert body["heat_readings"][0]["status"] == "WARM"


async def test_returns_empty_lists_for_a_symbol_with_no_readings_today() -> None:
    async with await _client() as client:
        response = await client.get(
            "/api/stock-radar/TEST-NO-SUCH-SYMBOL/intraday", params={"since": "2026-09-10T00:00:00Z"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["interaction_readings"] == []
    assert body["heat_readings"] == []


async def test_since_filters_out_readings_before_the_window() -> None:
    before_window = datetime(2026, 9, 9, 9, 0, tzinfo=UTC)
    interaction_score = InteractionScore(0.0, 0.0, 0.0, InteractionLabel.NEUTRAL)

    async with session_scope() as session:
        await persist_interaction_score(
            session, symbol=_TEST_SYMBOL, market_regime="NEUTRAL", benchmark_return_pct=0.0,
            stock_return_pct=0.0, foreign_net_today=0.0, institution_net_today=0.0,
            score=interaction_score, observed_at=before_window,
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get(
            f"/api/stock-radar/{_TEST_SYMBOL}/intraday", params={"since": "2026-09-10T00:00:00Z"}
        )

    assert response.status_code == 200
    assert response.json()["interaction_readings"] == []
