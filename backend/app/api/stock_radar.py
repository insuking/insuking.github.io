"""Stock radar read API (P28).

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

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.models import SecurityRow
from app.db.session import session_scope
from app.stock_radar.persistence import get_latest_scan

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
