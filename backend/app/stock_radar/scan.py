"""Stock radar scan orchestration (P23).

Wires the P23 scoring engine (`app/stock_radar/scoring.py`) into a ranked
PRE-BREAKOUT candidate list - the stock-market analogue of
`app/scan/crypto_scan.py`, reusing the same P4 ranking funnel
(`app/radar/ranking.py`) rather than reimplementing ranking.

Split into a pure layer and a thin I/O layer, same shape as
`app/scan/crypto_scan.py`:

- `rank_prebreakout_candidates()` is pure (no I/O) and does all the real
  work - fully unit-testable without a KIS connection.
- `scan_stock_universe()` is the thin async wrapper that fetches real daily
  prices via `KisRestClient.get_daily_prices()` and calls the pure
  function. Sequential, no throttling: unlike Upbit (P7/P23's crypto
  scan), where a real docker-compose run actually tripped a 429 and gave
  concrete grounds to add a rate limiter, KIS's real request-rate behavior
  has never been observed by this project (no credentials provisioned yet
  - see docs/KIS_SETUP.md) - inventing a throttle number here would be a
  guess, not a fix for an observed problem. Add one once a real run shows
  it's needed.

The KOSPI/KOSDAQ benchmark series is a caller-supplied `benchmark_candles`
parameter rather than fetched internally: KIS's index-quote endpoint uses a
different `FID_COND_MRKT_DIV_CODE` ("U", not the stock-quote "J") that this
phase has not independently verified (KIS's docs portal and the
`open-trading-api` GitHub sample were both unreachable while this was
written). Guessing at an unverified index-fetch call here would risk
silently returning garbage relative-strength numbers into every score;
`scripts/scan_stocks.py` documents this as an explicit open item to verify
once real credentials exist.
"""

from __future__ import annotations

from app.integrations.kis.rest_client import KisRestClient
from app.models.domain import Candle
from app.radar.ranking import RadarFunnel, rank_candidates
from app.stock_radar.scoring import (
    DEFAULT_WEIGHTS,
    PreBreakoutScore,
    PreBreakoutWeights,
    score_prebreakout,
)


def rank_prebreakout_candidates(
    symbol_candles: dict[str, list[Candle]],
    benchmark_candles: list[Candle],
    weights: PreBreakoutWeights = DEFAULT_WEIGHTS,
    top_n: int = 30,
) -> list[PreBreakoutScore]:
    """Score every symbol with enough history, rank by `total_score`
    (reusing P4's `rank_candidates()` funnel), and return the top `top_n`
    full `PreBreakoutScore` records (not just symbol+score) so a caller
    keeps the explanation factors for display/persistence. Symbols with
    too little history are silently skipped, never scored with fabricated
    data - matches `score_prebreakout()`'s own `None`-on-insufficient-data
    gating.
    """
    scores: dict[str, PreBreakoutScore] = {}
    for symbol, candles in symbol_candles.items():
        result = score_prebreakout(symbol, candles, benchmark_candles, weights=weights)
        if result is not None:
            scores[symbol] = result

    funnel: RadarFunnel = rank_candidates([(symbol, s.total_score) for symbol, s in scores.items()])
    return [scores[c.symbol] for c in funnel.top200[:top_n]]


async def scan_stock_universe(
    rest: KisRestClient,
    symbols: list[str],
    benchmark_candles: list[Candle],
    start_date: str,
    end_date: str,
    weights: PreBreakoutWeights = DEFAULT_WEIGHTS,
    top_n: int = 30,
) -> list[PreBreakoutScore]:
    """Fetch each symbol's real daily price history and rank them. `symbols`
    is caller-supplied rather than pulled from a KRX master-file download:
    this project has no verified master-file parser yet (see
    docs/KIS_SETUP.md and `app/db/models.py`'s `SecurityRow` for the
    `securities` table this would populate) - seed it manually or via
    `scripts/scan_stocks.py`'s symbol list for now.
    """
    symbol_candles: dict[str, list[Candle]] = {}
    for symbol in symbols:
        candles = await rest.get_daily_prices(symbol, start_date, end_date)
        if candles:
            symbol_candles[symbol] = candles

    return rank_prebreakout_candidates(symbol_candles, benchmark_candles, weights=weights, top_n=top_n)
