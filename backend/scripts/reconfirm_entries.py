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
which isn't what "overnight re-ranking" means. `reference_close`,
`max_available`, and the `positive`/`negative` score factors (P31 -
needed for the `reasons`/`risks` a persisted `Recommendation` carries)
come back out of `radar_scores.explanation`'s JSON blob (see
`persistence.py`'s docstring for why that's not a dedicated column).

**P31**: a CONFIRMED verdict is no longer just printed - it's turned
into a real `Recommendation` (`app/stock_radar/recommendation.py`) and
persisted, the same real gap `scripts/scan_crypto.py` already closed for
CRYPTO. Every run clears this script's own previously-persisted
`stock-radar-%` rows first (idempotent replace, same pattern as
`scan_crypto.py`'s `scan-crypto-%`), so a symbol that's no longer
CONFIRMED on a later run doesn't linger as a stale recommendation.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, ".")

import httpx
from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models import RadarScoreRow
from app.db.models import Recommendation as RecommendationRow
from app.db.session import session_scope
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.rest_client import KOSPI_INDEX_CODE, KisRestClient
from app.models.domain import Recommendation
from app.radar.regime import MarketRegime, classify_market_regime
from app.stock_radar.persistence import get_latest_scan
from app.stock_radar.scan import build_confirmed_recommendations, reconfirm_candidates
from app.stock_radar.scoring import PreBreakoutScore, ScoreFactor

_REGIME_HISTORY_DAYS = 30  # only need enough for a 20-day moving-average regime read
_ATR_HISTORY_DAYS = 45  # comfortably covers ATR(14) plus a few extra trading days
_DEFAULT_BUYING_POWER = 10_000_000.0  # KRW placeholder - see module docstring, same as scan_crypto.py's


def _to_score(row: RadarScoreRow) -> PreBreakoutScore | None:
    try:
        explanation = json.loads(row.explanation)
        reference_close = float(explanation["reference_close"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    positive = [ScoreFactor(**f) for f in explanation.get("positive", [])]
    negative = [ScoreFactor(**f) for f in explanation.get("negative", [])]
    return PreBreakoutScore(
        symbol=row.symbol,
        total_score=row.prebreakout_score,
        max_available=explanation.get("max_available", row.prebreakout_score),
        reference_close=reference_close,
        positive=positive,
        negative=negative,
    )


async def _persist_recommendations(recommendations: list[Recommendation]) -> None:
    async with session_scope() as session:
        await session.execute(delete(RecommendationRow).where(RecommendationRow.id.like("stock-radar-%")))
        for rec in recommendations:
            session.add(
                RecommendationRow(
                    id=rec.id,
                    symbol=rec.symbol,
                    asset_type=rec.asset_type.value,
                    score=rec.score,
                    state=rec.state,
                    entry_low=rec.entry_low,
                    entry_high=rec.entry_high,
                    stop_price=rec.stop_price,
                    t1_price=rec.t1_price,
                    t1_percent=rec.t1_percent,
                    t2_price=rec.t2_price,
                    t2_percent=rec.t2_percent,
                    runner_percent=rec.runner_percent,
                    expected_max_loss=rec.expected_max_loss,
                    risk_reward=rec.risk_reward,
                    reasons=json.dumps(rec.reasons, ensure_ascii=False),
                    risks=json.dumps(rec.risks, ensure_ascii=False),
                    created_at=rec.created_at,
                    expires_at=rec.expires_at,
                )
            )
        await session.commit()


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

        buying_power_raw = os.environ.get("STOCK_SCAN_ACCOUNT_BUYING_POWER")
        if buying_power_raw is None:
            print(
                f"\nSTOCK_SCAN_ACCOUNT_BUYING_POWER not set - using a {_DEFAULT_BUYING_POWER:,.0f} KRW "
                "placeholder for position sizing. Set it to your real KIS buying power for accurate sizing."
            )
            account_buying_power = _DEFAULT_BUYING_POWER
        else:
            account_buying_power = float(buying_power_raw)

        atr_end_date = end_date
        atr_start_date = (datetime.now(UTC) - timedelta(days=_ATR_HISTORY_DAYS)).strftime("%Y%m%d")
        recommendations = await build_confirmed_recommendations(
            rest, scores, confirmations, account_buying_power, atr_start_date, atr_end_date
        )

    await _persist_recommendations(recommendations)

    if recommendations:
        print(f"\nPersisted {len(recommendations)} recommendation(s) - now visible on the 추천 tab:")
        for rec in recommendations:
            print(f"  {rec.symbol}: entry {rec.entry_low:,.0f}~{rec.entry_high:,.0f} / stop {rec.stop_price:,.0f}")
    else:
        print("\nNo CONFIRMED candidate produced a valid recommendation - nothing persisted this run.")


if __name__ == "__main__":
    asyncio.run(run())
