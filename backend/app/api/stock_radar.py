"""Stock radar read API (P28, extended in P41).

Backs the new 종목레이더 tab with the most recent PRE-BREAKOUT scan
already written to `radar_scores`/`securities` by `scripts/scan_stocks.py`
(P23/P25/P26/P27). Read-only, same shape as `dashboard.py`: convert real
DB rows into a typed response, never fabricate a scan that hasn't run
yet - an empty candidate list on a fresh deployment (or one where the
scan script has never been run) is the honest answer, not sample data
(see `dashboard.py`'s own module docstring for the same rule).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.models import SecurityRow
from app.db.session import session_scope
from app.scheduler.market_hours import KST
from app.stock_radar.persistence import get_latest_scan
from app.stock_radar.regime_persistence import (
    get_intraday_heat_readings,
    get_intraday_interaction_readings,
)

router = APIRouter(prefix="/api/stock-radar", tags=["stock-radar"])


class ScoreFactorOut(BaseModel):
    factor: str
    points: float
    detail: str


class StockRadarCandidateOut(BaseModel):
    symbol: str
    name: str | None
    rank: int | None
    total_score: float
    max_available: float
    positive: list[ScoreFactorOut]
    negative: list[ScoreFactorOut]


class StockRadarLatestOut(BaseModel):
    scan_run_id: str | None
    scored_at: str | None
    candidates: list[StockRadarCandidateOut]


@router.get("/latest", response_model=StockRadarLatestOut)
async def get_latest() -> StockRadarLatestOut:
    async with session_scope() as session:
        rows = await get_latest_scan(session)

        candidates: list[StockRadarCandidateOut] = []
        for row in rows:
            security = await session.get(SecurityRow, row.symbol)
            try:
                explanation = json.loads(row.explanation)
            except json.JSONDecodeError:
                explanation = {}

            candidates.append(
                StockRadarCandidateOut(
                    symbol=row.symbol,
                    name=security.name if security is not None else None,
                    rank=row.rank,
                    total_score=row.prebreakout_score,
                    max_available=explanation.get("max_available", row.prebreakout_score),
                    positive=[ScoreFactorOut(**f) for f in explanation.get("positive", [])],
                    negative=[ScoreFactorOut(**f) for f in explanation.get("negative", [])],
                )
            )

    return StockRadarLatestOut(
        scan_run_id=rows[0].scan_run_id if rows else None,
        scored_at=rows[0].scored_at.isoformat() if rows else None,
        candidates=candidates,
    )


class InteractionReadingOut(BaseModel):
    observed_at: str
    market_regime: str
    benchmark_return_pct: float
    stock_return_pct: float
    interaction_score: float
    label: str


class HeatReadingOut(BaseModel):
    observed_at: str
    heat_score: float
    status: str
    return_1d_pct: float
    return_5d_pct: float


class StockRadarIntradayOut(BaseModel):
    symbol: str
    interaction_readings: list[InteractionReadingOut]
    heat_readings: list[HeatReadingOut]


def _start_of_kst_day(now: datetime | None = None) -> datetime:
    now_kst = (now or datetime.now(UTC)).astimezone(KST)
    return now_kst.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/{symbol}/intraday", response_model=StockRadarIntradayOut)
async def get_intraday(symbol: str, since: datetime | None = None) -> StockRadarIntradayOut:
    """P41: `symbol`'s real intraday history of P34 interaction-score and
    P35 heat readings - every real `reconfirm_entries.py` run that scored
    it, not just the latest. Defaults to today's KST calendar day
    (`since` unset) - "intraday" means "today's readings", not the whole
    history; pass `since` explicitly to look further back. An empty
    result on a fresh deployment, or for a symbol that was never
    CONFIRMED today, is the honest answer, not a fabricated timeline.
    """
    window_start = since if since is not None else _start_of_kst_day()

    async with session_scope() as session:
        interaction_rows = await get_intraday_interaction_readings(session, symbol, since=window_start)
        heat_rows = await get_intraday_heat_readings(session, symbol, since=window_start)

    return StockRadarIntradayOut(
        symbol=symbol,
        interaction_readings=[
            InteractionReadingOut(
                observed_at=row.observed_at.isoformat(),
                market_regime=row.market_regime,
                benchmark_return_pct=row.benchmark_return_pct,
                stock_return_pct=row.stock_return_pct,
                interaction_score=row.interaction_score,
                label=row.label,
            )
            for row in interaction_rows
        ],
        heat_readings=[
            HeatReadingOut(
                observed_at=row.observed_at.isoformat(),
                heat_score=row.heat_score,
                status=row.status,
                return_1d_pct=row.return_1d_pct,
                return_5d_pct=row.return_5d_pct,
            )
            for row in heat_rows
        ],
    )
