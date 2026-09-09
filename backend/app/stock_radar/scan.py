"""Stock radar scan orchestration (P23, extended in P27).

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

The KOSPI/KOSDAQ benchmark series stays a caller-supplied `benchmark_candles`
parameter rather than fetched internally here - this module has no opinion
on where it came from. `scripts/scan_stocks.py` is the caller that decides:
it now calls `KisRestClient.get_index_daily_prices()` for a real KOSPI
series, falling back to a flat placeholder only if that call fails (see
that script's module docstring). `get_index_daily_prices()`'s own docstring
still flags its field layout as not independently verified against real
KIS servers - that verification, and any fallout from it, lives there, not
in this module.
"""

from __future__ import annotations

from app.integrations.kis.errors import KisApiError
from app.integrations.kis.rest_client import KisRestClient
from app.models.domain import Candle
from app.radar.ranking import RadarFunnel, rank_candidates
from app.radar.regime import MarketRegime
from app.stock_radar.entry_confirmation import (
    DEFAULT_THRESHOLDS,
    EntryConfirmation,
    EntryConfirmationThresholds,
    EntryVerdict,
    confirm_entry,
)
from app.stock_radar.investor_flow import InvestorFlowBar
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
    symbol_flow_bars: dict[str, list[InvestorFlowBar]] | None = None,
) -> list[PreBreakoutScore]:
    """Score every symbol with enough history, rank by `total_score`
    (reusing P4's `rank_candidates()` funnel), and return the top `top_n`
    full `PreBreakoutScore` records (not just symbol+score) so a caller
    keeps the explanation factors for display/persistence. Symbols with
    too little history are silently skipped, never scored with fabricated
    data - matches `score_prebreakout()`'s own `None`-on-insufficient-data
    gating.

    `symbol_flow_bars` (P25, optional): per-symbol investor-flow history,
    passed straight through to `score_prebreakout()`'s own
    `investor_flow_bars` param when present for that symbol - see that
    function's docstring for how omitting it (the default) leaves scoring
    exactly as it was before P25.
    """
    scores: dict[str, PreBreakoutScore] = {}
    for symbol, candles in symbol_candles.items():
        flow_bars = (symbol_flow_bars or {}).get(symbol)
        result = score_prebreakout(symbol, candles, benchmark_candles, weights=weights, investor_flow_bars=flow_bars)
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
) -> tuple[list[PreBreakoutScore], dict[str, str]]:
    """Fetch each symbol's real daily price history and rank them. `symbols`
    stays caller-supplied rather than this function pulling the KRX
    universe itself - `app/integrations/kis/krx_master.py` (P30) is the
    real master-file downloader/parser, wired in at `scripts/
    scan_stocks.py`'s `STOCK_SCAN_UNIVERSE=FULL` layer (which then narrows
    the full universe to a liquidity-ranked top-N before calling this
    function), not here - this function has no opinion on where its
    symbol list came from.

    Also returns a `symbol -> Korean name` dict (from the same daily-price
    call, via `KisRestClient.get_daily_prices_with_name()` - no extra
    round trip) for display purposes; a symbol is omitted if KIS didn't
    return a name for it.

    Also fetches each symbol's investor-flow history (P25, via
    `KisRestClient.get_investor_trend()` - one extra rate-limited call per
    symbol) and feeds it into scoring, so a real scan gets the
    `institutional_flow` factor without the caller having to do anything
    extra. Unlike the daily-price/name fetch above, this call is wrapped
    per-symbol: `get_investor_trend()`'s field layout is confirmed only
    against KIS's public sample repo, not yet against a live response from
    this project's own credentials (see docs/KIS_SETUP.md), so a bad guess
    there degrades that one symbol to the pre-P25 65-point ceiling instead
    of crashing the whole scan.
    """
    symbol_candles: dict[str, list[Candle]] = {}
    names: dict[str, str] = {}
    symbol_flow_bars: dict[str, list[InvestorFlowBar]] = {}
    for symbol in symbols:
        candles, name = await rest.get_daily_prices_with_name(symbol, start_date, end_date)
        if candles:
            symbol_candles[symbol] = candles
        if name:
            names[symbol] = name
        try:
            flow_bars = await rest.get_investor_trend(symbol)
        except (KisApiError, KeyError, ValueError):
            flow_bars = []
        if flow_bars:
            symbol_flow_bars[symbol] = flow_bars

    results = rank_prebreakout_candidates(
        symbol_candles, benchmark_candles, weights=weights, top_n=top_n, symbol_flow_bars=symbol_flow_bars
    )
    return results, names


async def reconfirm_candidates(
    rest: KisRestClient,
    results: list[PreBreakoutScore],
    regime: MarketRegime,
    thresholds: EntryConfirmationThresholds = DEFAULT_THRESHOLDS,
) -> list[EntryConfirmation]:
    """P27's thin I/O wrapper: fetch one fresh quote per already-scored
    candidate (via `KisRestClient.get_quote()` - already P3-verified, no
    new endpoint risk here) and run each through `confirm_entry()`. A
    quote fetch failing for one symbol degrades that symbol to REJECTED
    with the failure as its reason, rather than crashing the whole
    re-confirmation pass - matches `scan_stock_universe()`'s own
    per-symbol degrade-not-crash pattern for `get_investor_trend()`.

    This function's real-world correctness can only be judged during real
    KRX trading hours - `get_quote()` returns whatever KIS's servers
    currently report, and outside trading hours that's just the same
    stale closing price `results` was already scored from, which would
    make every gap read as ~0% and look "confirmed" for reasons that have
    nothing to do with this logic actually working. See
    `scripts/reconfirm_entries.py` for the real entrypoint and its own
    warning about when running it actually proves anything.
    """
    confirmations: list[EntryConfirmation] = []
    for score in results:
        try:
            quote = await rest.get_quote(score.symbol)
            confirmations.append(confirm_entry(score, quote.price, regime, thresholds))
        except (KisApiError, KeyError, ValueError) as exc:
            confirmations.append(
                EntryConfirmation(
                    symbol=score.symbol,
                    verdict=EntryVerdict.REJECTED,
                    gap_pct=0.0,
                    reasons=[f"실시간 시세 조회 실패: {exc!r}"],
                )
            )
    return confirmations
