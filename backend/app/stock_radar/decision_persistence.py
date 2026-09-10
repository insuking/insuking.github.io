"""P36 persistence: `daily_decisions` - one row per `scripts/
reconfirm_entries.py` run recording `app/stock_radar/decision.py`'s
overall call for that run, so the 시장 tab (and any later review) has a
real, queryable "오늘의 판정" rather than something recomputed on every
page load from scratch.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyDecisionRow
from app.stock_radar.decision import DecisionState, EntryDecision


async def persist_daily_decision(
    session: AsyncSession,
    market_regime: str,
    daily_state: DecisionState,
    top_symbol: str | None,
    top_symbol_name: str | None,
    top_decision: EntryDecision | None,
    entry_filters_passed: int | None = None,
    entry_filters_total: int | None = None,
    observed_at: datetime | None = None,
) -> None:
    """Appends one row - does not commit, same convention as
    `app.stock_radar.regime_persistence`'s persist functions."""
    session.add(
        DailyDecisionRow(
            observed_at=observed_at or datetime.now(UTC),
            market_regime=market_regime,
            minimum_score=top_decision.minimum_score if top_decision is not None else 0.0,
            decision_state=daily_state.value,
            top_symbol=top_symbol,
            top_symbol_name=top_symbol_name,
            top_normalized_score=top_decision.normalized_score if top_decision is not None else None,
            entry_filters_passed=entry_filters_passed,
            entry_filters_total=entry_filters_total,
            reason=top_decision.reason if top_decision is not None else "오늘 재확인된 CONFIRMED 후보가 없습니다",
            created_at=datetime.now(UTC),
        )
    )


async def get_latest_daily_decision(session: AsyncSession) -> DailyDecisionRow | None:
    """Most recent row, or `None` on a fresh deployment where
    `reconfirm_entries.py` has never run yet - an honest absence, not a
    guessed NO_TRADE_DAY."""
    return (
        await session.execute(select(DailyDecisionRow).order_by(DailyDecisionRow.observed_at.desc()).limit(1))
    ).scalar_one_or_none()
