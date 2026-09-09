#!/usr/bin/env python3
"""P27: re-confirm the most recent stock scan's candidates against a fresh
KIS quote, right before acting on them.

**This script's output only means something during real KRX trading
hours** (KOSPI/KOSDAQ, roughly 09:00-15:30 KST on a trading day). Outside
that window, `KisRestClient.get_quote()` returns the same stale closing
price the candidates were already scored from - every gap will read as
~0% and look "CONFIRMED" for a reason that has nothing to do with
`confirm_entry()` actually working. Running this at 2am and seeing all
CONFIRMED is not a successful test; it is not a test at all. See
`app/stock_radar/entry_confirmation.py` and `scan.py`'s
`reconfirm_candidates()` for the pure logic and its own version of this
same warning.

Reads the most recent scan's results from `radar_scores` (written by
`scripts/scan_stocks.py` via `persist_scan_results()`) rather than
re-running a scan itself - re-scoring here would just recompute the same
already-stored PRE-BREAKOUT score from the same stale daily candles,
which isn't what "overnight re-ranking" means. `reference_close` and
`max_available` come back out of `radar_scores.explanation`'s JSON blob
(see `persistence.py`'s docstring for why that's not a dedicated column).
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, ".")

import httpx

from app.core.config import get_settings
from app.db.models import RadarScoreRow
from app.db.session import session_scope
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.rest_client import KOSPI_INDEX_CODE, KisRestClient
from app.radar.regime import MarketRegime, classify_market_regime
from app.stock_radar.persistence import get_latest_scan
from app.stock_radar.scan import reconfirm_candidates
from app.stock_radar.scoring import PreBreakoutScore

_REGIME_HISTORY_DAYS = 30  # only need enough for a 20-day moving-average regime read


def _to_score(row: RadarScoreRow) -> PreBreakoutScore | None:
    try:
        explanation = json.loads(row.explanation)
        reference_close = float(explanation["reference_close"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    return PreBreakoutScore(
        symbol=row.symbol,
        total_score=row.prebreakout_score,
        max_available=explanation.get("max_available", row.prebreakout_score),
        reference_close=reference_close,
    )


async def run() -> None:
    settings = get_settings()
    if not settings.kis_configured:
        print("KIS_APP_KEY/KIS_APP_SECRET are not set - see docs/KIS_SETUP.md. Nothing to reconfirm yet.")
        return

    async with session_scope() as session:
        rows = await get_latest_scan(session)

    if not rows:
        print("No stored scan found - run scripts/scan_stocks.py first.")
        return

    scores = [s for row in rows if (s := _to_score(row)) is not None]
    if not scores:
        print("Stored scan rows exist but none carry a usable reference_close - nothing to reconfirm.")
        return

    print(f"Re-confirming {len(scores)} candidate(s) from scan_run_id={rows[0].scan_run_id}.\n")

    end_date = datetime.now(UTC).strftime("%Y%m%d")
    start_date = (datetime.now(UTC) - timedelta(days=_REGIME_HISTORY_DAYS)).strftime("%Y%m%d")

    async with httpx.AsyncClient(base_url=settings.kis_rest_base_url) as client:
        auth = KisAuth(client=client, settings=settings)
        rest = KisRestClient(client, auth)

        try:
            benchmark_candles = await rest.get_index_daily_prices(KOSPI_INDEX_CODE, start_date, end_date)
            regime = classify_market_regime(benchmark_candles) if benchmark_candles else MarketRegime.NEUTRAL
        except (KisApiError, KeyError, ValueError) as exc:
            print(f"WARNING: could not fetch a fresh KOSPI regime read ({exc!r}) - treating regime as NEUTRAL.\n")
            regime = MarketRegime.NEUTRAL

        print(f"시장 상황 (재확인 시점 기준): {regime.value}\n")

        confirmations = await reconfirm_candidates(rest, scores, regime)

    for c in confirmations:
        print(f"[{c.verdict.value}] {c.symbol}: gap {c.gap_pct:+.1f}%")
        for reason in c.reasons:
            print(f"    - {reason}")


if __name__ == "__main__":
    asyncio.run(run())
