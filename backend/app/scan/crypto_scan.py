"""Real-market crypto recommendation scan (P23).

Wires together already-built, already-tested pure functions from P4/P8/P9
with real Upbit REST data (P7) to produce up to `TOP_N_RECOMMENDATIONS`
CRYPTO `Recommendation`s from the live KRW market. No new feature-calculation
or recommendation-generation logic lives here - this module is only
*input-gathering*: fetch the real universe, rank it, compute the same
signals P4/P8 already define, and hand them to P6's `build_recommendation()`
unchanged.

Deliberate simplification, documented rather than hidden: a fresh scan has
no persisted prior `RadarState` to smooth against, so this uses P4's
stateless `next_state()` from `RadarState.STEALTH` for one bar rather than
P9's `CryptoRadarStateTracker` hysteresis (which requires several
consecutive confirming bars before committing a state change - meaningless
for a single one-shot snapshot). Pump-risk is still applied as an immediate
override on top of that, matching the tracker's own priority order
(docs/MASTER_SPEC.md: "Position Protection" before smoothing).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.integrations.upbit.rest_client import UpbitRestClient
from app.models.domain import AssetType, Candle, Recommendation
from app.radar.crypto_features import (
    classify_btc_regime,
    pump_risk_score,
    relative_strength_vs_btc,
    relative_volume,
)
from app.radar.crypto_state import DEFAULT_PUMP_RISK_THRESHOLD
from app.radar.features import close_location_value, opening_range
from app.radar.ranking import rank_candidates
from app.radar.state import RadarState, next_state
from app.recommendation.engine import (
    RecommendationInputs,
    build_recommendation,
    score_recommendation,
)

BENCHMARK_MARKET = "KRW-BTC"
CANDLE_UNIT_MINUTES = 1
CANDLE_COUNT = 200
OPENING_RANGE_BARS = 15
LIQUIDITY_PREFILTER_SIZE = 30
MAX_CONCURRENT_CANDLE_FETCHES = 5
TOP_N_RECOMMENDATIONS = 5


@dataclass
class ScannedCandidate:
    """One market's computed signals - kept around for scan output/debugging
    even for candidates that don't end up producing a recommendation."""

    market: str
    price: float
    rvol: float
    clv: float
    relative_strength_value: float
    pump_risk: float
    radar_state: RadarState
    breakout_level: float
    structural_stop: float
    score: float


def _chronological(candles: list[Candle]) -> list[Candle]:
    """Upbit's REST candle endpoint returns most-recent-bar-first; every P4/P8
    feature function assumes ascending (oldest-first) order (docs/UPBIT_NOTES.md)."""
    return list(reversed(candles))


def _evaluate_candidate(market: str, candles: list[Candle], benchmark_candles: list[Candle]) -> ScannedCandidate | None:
    if len(candles) < OPENING_RANGE_BARS + 1:
        return None

    opening = opening_range(candles, OPENING_RANGE_BARS)
    latest = candles[-1]
    history = candles[:-1]
    avg_volume = sum(c.volume for c in history) / len(history) if history else 0.0
    rvol = relative_volume(latest.volume, avg_volume)
    clv = close_location_value(latest)
    pump_risk = pump_risk_score(candles)
    relative_strength_value = relative_strength_vs_btc(candles, benchmark_candles)

    if pump_risk >= DEFAULT_PUMP_RISK_THRESHOLD:
        radar_state = RadarState.PUMP_RISK
    else:
        radar_state = next_state(RadarState.STEALTH, latest.close, opening.high, rvol, clv)

    score = score_recommendation(
        radar_state, rvol, relative_strength_value, classify_btc_regime(benchmark_candles)
    )

    return ScannedCandidate(
        market=market,
        price=latest.close,
        rvol=rvol,
        clv=clv,
        relative_strength_value=relative_strength_value,
        pump_risk=pump_risk,
        radar_state=radar_state,
        breakout_level=opening.high,
        structural_stop=opening.low,
        score=score,
    )


async def scan_crypto_market(
    rest: UpbitRestClient,
    account_buying_power: float,
    top_n: int = TOP_N_RECOMMENDATIONS,
) -> list[Recommendation]:
    """Fetch the real KRW universe, rank it by liquidity then by signal score,
    and return up to `top_n` real `Recommendation`s (fewer if fewer candidates
    are actually eligible - never padded to hit a count)."""
    universe = await rest.get_krw_market_universe()
    if not universe:
        return []

    summaries = await rest.get_tickers_summary(universe)
    by_liquidity = sorted(summaries, key=lambda s: s.acc_trade_price_24h, reverse=True)
    candidate_markets = [s.market for s in by_liquidity if s.market != BENCHMARK_MARKET][
        :LIQUIDITY_PREFILTER_SIZE
    ]

    benchmark_candles = _chronological(
        await rest.get_candles(BENCHMARK_MARKET, CANDLE_UNIT_MINUTES, CANDLE_COUNT)
    )
    regime = classify_btc_regime(benchmark_candles)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CANDLE_FETCHES)

    async def fetch(market: str) -> tuple[str, list[Candle]]:
        async with semaphore:
            candles = await rest.get_candles(market, CANDLE_UNIT_MINUTES, CANDLE_COUNT)
        return market, _chronological(candles)

    fetched = await asyncio.gather(*(fetch(market) for market in candidate_markets))

    candidates = [
        candidate
        for market, candles in fetched
        if (candidate := _evaluate_candidate(market, candles, benchmark_candles)) is not None
    ]

    ranked = rank_candidates([(c.market, c.score) for c in candidates])
    by_market = {c.market: c for c in candidates}

    recommendations: list[Recommendation] = []
    for ranked_candidate in ranked.top30:
        if len(recommendations) >= top_n:
            break
        scanned = by_market[ranked_candidate.symbol]
        inputs = RecommendationInputs(
            symbol=scanned.market,
            asset_type=AssetType.CRYPTO,
            price=scanned.price,
            breakout_level=scanned.breakout_level,
            structural_stop=scanned.structural_stop,
            rvol=scanned.rvol,
            clv=scanned.clv,
            relative_strength_value=scanned.relative_strength_value,
            regime=regime,
            radar_state=scanned.radar_state,
            account_buying_power=account_buying_power,
        )
        rec = build_recommendation(inputs)
        if rec is not None:
            recommendations.append(rec)

    return recommendations
