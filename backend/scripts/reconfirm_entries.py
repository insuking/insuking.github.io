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

**P33**: each persisted `Recommendation` also carries the symbol's
Korean company name (`app/stock_radar/persistence.py`'s
`get_security_names()`, reading the same `securities` table
`scan_stocks.py` already upserts) - the 추천 탭 tab shown a bare 6-digit
KRX code with no name told a user nothing.

**P35**: `build_confirmed_recommendations()` now also returns a
`HeatScore` per symbol it evaluated (`app/stock_radar/overheat.py`) and
already excludes a TOO_LATE candidate from `recommendations` itself -
every one of those readings, not just the survivors, is persisted to
`overheat_scores` here so a later review can see what got filtered and
why, not just what got through.

**P34**: for each CONFIRMED symbol, also computes and persists a Market
Regime x Relative Strength interaction reading
(`app/stock_radar/regime_interaction.py`) - the benchmark's 1-day return
from the same KOSPI candles already fetched for the regime read above,
the stock's 1-day return reused directly from its own `HeatScore`
(`return_1d_pct` - the exact same number, not recomputed), and today's/
yesterday's foreign+institution net flow via one extra
`KisRestClient.get_investor_trend()` call per CONFIRMED symbol (the same
P25 endpoint `scan_stocks.py` already uses, not a new integration risk).
Only run for CONFIRMED symbols, not every scored candidate, to keep this
script's request volume roughly what it already was.

**P36**: also computes `app/stock_radar/decision.py`'s per-symbol
STRONG_BUY/BUY/WATCH/NO_BUY call (using `score.positive`'s length as an
honest proxy for "how many entry filters passed" - see `_entry_filters()`
below for why) for every CONFIRMED symbol, picks whichever ranks best,
and persists the resulting day-level call (including the honest
NO_TRADE_DAY outcome) to `daily_decisions` - "오늘의 판정" on the 시장 tab.
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
from app.stock_radar.decision import (
    DecisionState,
    EntryDecision,
    decide_daily_state,
    decide_entry_state,
)
from app.stock_radar.decision_persistence import persist_daily_decision
from app.stock_radar.entry_confirmation import EntryVerdict
from app.stock_radar.overheat import HeatScore, HeatStatus
from app.stock_radar.persistence import get_latest_scan, get_security_names
from app.stock_radar.regime_interaction import compute_interaction_score
from app.stock_radar.regime_persistence import persist_interaction_score, upsert_heat_score
from app.stock_radar.scan import build_confirmed_recommendations, reconfirm_candidates
from app.stock_radar.scoring import SCORE_MAX_AVAILABLE, PreBreakoutScore, ScoreFactor

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
                    name=rec.name,
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


async def _persist_heat_scores(heat_scores: dict[str, HeatScore], observed_at: datetime) -> None:
    async with session_scope() as session:
        for symbol, score in heat_scores.items():
            await upsert_heat_score(session, symbol=symbol, score=score, observed_at=observed_at)
        await session.commit()


async def _persist_interaction_scores(
    rest: KisRestClient,
    confirmed_symbols: list[str],
    heat_scores: dict[str, HeatScore],
    benchmark_return_pct: float,
    regime: MarketRegime,
    observed_at: datetime,
) -> None:
    """One `get_investor_trend()` call per CONFIRMED symbol - a bad or
    missing flow response degrades that one symbol to a flow-less
    interaction read (no FLOW_NOT_PERSISTENT/market-plunge-with-flow
    bonus, price-only resilience still scored) rather than skipping it
    entirely, matching `scan_stock_universe()`'s own per-symbol
    degrade-not-crash pattern for this same endpoint.
    """
    async with session_scope() as session:
        for symbol in confirmed_symbols:
            heat = heat_scores.get(symbol)
            if heat is None:
                continue

            foreign_today = institution_today = 0.0
            foreign_prev: float | None = None
            institution_prev: float | None = None
            try:
                flow_bars = await rest.get_investor_trend(symbol)
            except (KisApiError, KeyError, ValueError):
                flow_bars = []
            if flow_bars:
                foreign_today = flow_bars[-1].foreign_net_qty
                institution_today = flow_bars[-1].institution_net_qty
                if len(flow_bars) >= 2:
                    foreign_prev = flow_bars[-2].foreign_net_qty
                    institution_prev = flow_bars[-2].institution_net_qty

            score = compute_interaction_score(
                benchmark_return_pct=benchmark_return_pct,
                stock_return_pct=heat.return_1d_pct,
                foreign_net_today=foreign_today,
                institution_net_today=institution_today,
                foreign_net_prev_day=foreign_prev,
                institution_net_prev_day=institution_prev,
            )
            await persist_interaction_score(
                session,
                symbol=symbol,
                market_regime=regime.value,
                benchmark_return_pct=benchmark_return_pct,
                stock_return_pct=heat.return_1d_pct,
                foreign_net_today=foreign_today,
                institution_net_today=institution_today,
                score=score,
                observed_at=observed_at,
            )
        await session.commit()


_STATE_RANK = {
    DecisionState.STRONG_BUY: 3,
    DecisionState.BUY: 2,
    DecisionState.WATCH: 1,
    DecisionState.NO_BUY: 0,
}


def _entry_filters(score: PreBreakoutScore) -> tuple[int, int]:
    """(filters_passed, filters_total) - a real, honest proxy for the
    spec's "5개 진입필터" this project has no literal VWAP/Opening-Support/
    RVOL/Flow/RS filter bank for (those are the *crypto* radar's P4
    concepts - see `app/radar/ranking.py` - the stock radar's own signal
    set is `scoring.py`'s compression/volume/value/distance/ATR/OBV/
    market-RS[/institutional-flow] factors instead). `filters_passed` is
    how many of those actually cleared the strong-signal bar
    (`score.positive`'s length - the same >=0.7-fraction threshold
    `scoring.py` already uses to decide what counts as a real positive,
    not a new number invented here); `filters_total` is how many factors
    were even evaluated for this symbol (7, or 8 when P25's investor-flow
    factor was also scored - see `PreBreakoutWeights.institutional_flow`'s
    docstring for why that's conditional).
    """
    filters_total = 8 if score.max_available > SCORE_MAX_AVAILABLE else 7
    return len(score.positive), filters_total


async def _persist_daily_decision(
    scores_by_symbol: dict[str, PreBreakoutScore],
    confirmed_symbols: list[str],
    heat_scores: dict[str, HeatScore],
    names: dict[str, str],
    regime: MarketRegime,
    observed_at: datetime,
) -> None:
    """P36: `decide_entry_state()` for every CONFIRMED symbol that got a
    heat reading, then `decide_daily_state()` from whichever one ranks
    best (STRONG_BUY > BUY > WATCH > NO_BUY, tie-broken by score) - "오늘의
    판정" persisted once per run so the 시장 tab has a real answer to
    "is there anything worth buying today", including the honest
    NO_TRADE_DAY case.
    """
    best_symbol: str | None = None
    best_decision: EntryDecision | None = None
    best_filters: tuple[int, int] | None = None

    for symbol in confirmed_symbols:
        score = scores_by_symbol.get(symbol)
        heat = heat_scores.get(symbol)
        if score is None or heat is None:
            continue
        normalized_score = (score.total_score / score.max_available * 100) if score.max_available > 0 else 0.0
        filters_passed, filters_total = _entry_filters(score)
        decision = decide_entry_state(
            normalized_score=min(max(normalized_score, 0.0), 100.0),
            regime=regime,
            heat_status=heat.status,
            entry_filters_passed=filters_passed,
            entry_filters_total=filters_total,
        )
        if best_decision is None or (
            _STATE_RANK[decision.state],
            decision.normalized_score,
        ) > (_STATE_RANK[best_decision.state], best_decision.normalized_score):
            best_symbol, best_decision, best_filters = symbol, decision, (filters_passed, filters_total)

    daily_state = decide_daily_state(best_decision)
    async with session_scope() as session:
        await persist_daily_decision(
            session,
            market_regime=regime.value,
            daily_state=daily_state,
            top_symbol=best_symbol,
            top_symbol_name=names.get(best_symbol) if best_symbol else None,
            top_decision=best_decision,
            entry_filters_passed=best_filters[0] if best_filters else None,
            entry_filters_total=best_filters[1] if best_filters else None,
            observed_at=observed_at,
        )
        await session.commit()

    print(f"\n오늘의 판정 (P36): {daily_state.value}" + (f" ({best_symbol})" if best_symbol else ""))


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

    async with session_scope() as session:
        names = await get_security_names(session, [s.symbol for s in scores])

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
        recommendations, heat_scores = await build_confirmed_recommendations(
            rest, scores, confirmations, account_buying_power, atr_start_date, atr_end_date, names=names
        )

        too_late_symbols = [s for s, h in heat_scores.items() if h.status == HeatStatus.TOO_LATE]
        if too_late_symbols:
            print(f"\nTOO_LATE (신규 진입 제외): {', '.join(too_late_symbols)}")

        benchmark_return_pct = 0.0
        if len(benchmark_candles) >= 2:
            prev_close = benchmark_candles[-2].close
            if prev_close > 0:
                benchmark_return_pct = (benchmark_candles[-1].close / prev_close - 1) * 100

        confirmed_symbols = [c.symbol for c in confirmations if c.verdict == EntryVerdict.CONFIRMED]
        observed_at = datetime.now(UTC)
        await _persist_interaction_scores(
            rest, confirmed_symbols, heat_scores, benchmark_return_pct, regime, observed_at
        )

    await _persist_heat_scores(heat_scores, observed_at)
    await _persist_recommendations(recommendations)
    scores_by_symbol = {s.symbol: s for s in scores}
    await _persist_daily_decision(scores_by_symbol, confirmed_symbols, heat_scores, names, regime, observed_at)

    if recommendations:
        print(f"\nPersisted {len(recommendations)} recommendation(s) - now visible on the 추천 tab:")
        for rec in recommendations:
            print(f"  {rec.symbol}: entry {rec.entry_low:,.0f}~{rec.entry_high:,.0f} / stop {rec.stop_price:,.0f}")
    else:
        print("\nNo CONFIRMED candidate produced a valid recommendation - nothing persisted this run.")


if __name__ == "__main__":
    asyncio.run(run())
