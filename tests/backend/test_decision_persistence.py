"""P36 acceptance: decision_persistence.py against the real local Postgres."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.models import DailyDecisionRow
from app.db.session import session_scope
from app.stock_radar.decision import DecisionState, EntryDecision
from app.stock_radar.decision_persistence import get_latest_daily_decision, persist_daily_decision

pytestmark = [pytest.mark.P36, pytest.mark.asyncio]


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(DailyDecisionRow).where(DailyDecisionRow.market_regime == "TEST-REGIME"))
        await session.commit()


async def test_persist_and_read_back_a_strong_buy_day() -> None:
    decision = EntryDecision(DecisionState.STRONG_BUY, minimum_score=80.0, normalized_score=89.0, reason="테스트 이유")
    observed_at = datetime(2026, 9, 10, tzinfo=UTC)

    async with session_scope() as session:
        await persist_daily_decision(
            session,
            market_regime="TEST-REGIME",
            daily_state=DecisionState.STRONG_BUY,
            top_symbol="005930",
            top_symbol_name="삼성전자",
            top_decision=decision,
            entry_filters_passed=5,
            entry_filters_total=5,
            observed_at=observed_at,
        )
        await session.commit()

        latest = await get_latest_daily_decision(session)

    assert latest is not None
    assert latest.decision_state == "STRONG_BUY"
    assert latest.top_symbol == "005930"
    assert latest.top_symbol_name == "삼성전자"
    assert latest.top_normalized_score == pytest.approx(89.0)
    assert latest.entry_filters_passed == 5
    assert latest.market_regime == "TEST-REGIME"
    assert latest.observed_at == observed_at


async def test_persist_no_trade_day_without_a_top_decision() -> None:
    async with session_scope() as session:
        await persist_daily_decision(
            session,
            market_regime="TEST-REGIME",
            daily_state=DecisionState.NO_TRADE_DAY,
            top_symbol=None,
            top_symbol_name=None,
            top_decision=None,
        )
        await session.commit()

        latest = await get_latest_daily_decision(session)

    assert latest is not None
    assert latest.decision_state == "NO_TRADE_DAY"
    assert latest.top_symbol is None
    assert latest.top_normalized_score is None
    assert "재확인된" in (latest.reason or "")


async def test_get_latest_daily_decision_returns_the_most_recently_observed_row() -> None:
    older = datetime(2026, 9, 9, tzinfo=UTC)
    newer = datetime(2026, 9, 10, tzinfo=UTC)

    async with session_scope() as session:
        await persist_daily_decision(
            session, market_regime="TEST-REGIME", daily_state=DecisionState.NO_TRADE_DAY,
            top_symbol=None, top_symbol_name=None, top_decision=None, observed_at=older,
        )
        await persist_daily_decision(
            session, market_regime="TEST-REGIME", daily_state=DecisionState.BUY,
            top_symbol="000660", top_symbol_name="SK하이닉스",
            top_decision=EntryDecision(DecisionState.BUY, 80.0, 85.0, "이유"), observed_at=newer,
        )
        await session.commit()

        latest = await get_latest_daily_decision(session)

    assert latest is not None
    assert latest.observed_at == newer
    assert latest.decision_state == "BUY"
