"""P34: Market Regime x Relative Strength interaction engine.

Closes a real gap in the P23-P27 stock radar: market regime
(`app/radar/regime.py`) and a symbol's relative strength
(`app/radar/features.py`'s `relative_strength()`) were each scored
independently, but a stock holding up *while the market is falling* is a
qualitatively different, stronger signal than the same relative-strength
number in a flat or rising market - and a stock that outperformed
yesterday but underperforms today, right as the market turns down, is a
warning sign scoring the two independently can't see. This module scores
that interaction directly, as its own pure signal.

This is a genuinely new, separate signal - not a replacement for
`app/stock_radar/scoring.py`'s existing `market_relative_strength` factor
(single-day relative strength vs. yesterday) or the market-wide
`MarketRegime` gate `scripts/scan_stocks.py` already prints. It's kept
out of `PreBreakoutScore.total_score` entirely (never mixed into the
already-tuned 65/77-point ceiling) and reported as its own field
alongside the radar score, matching how the dashboard mockups in this
phase's own spec show "Radar" and "Market RS" as two separate numbers,
not one merged score.

Every threshold below is this project's own conservative, documented
starting point - tune from real morning runs once there's evidence to
tune from, the same "don't invent a number, then correct it from a real
signal" discipline already used for `DEFAULT_MAX_REQUESTS_PER_SECOND` in
`rest_client.py` and `EntryConfirmationThresholds` in
`entry_confirmation.py`. Two data sources this spec calls for do not
exist in this project and are honestly left out rather than faked:
sector-index return (`sector_return`/`sector_alpha` - no sector index
feed) and program-trading flow (`program_flow` - a separate KIS feed
this project has never touched, same gap already documented in
`investor_flow.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# "시장 급락"/weak-market threshold - the spec's own -1.5% example, reused
# for both the resilience score and the "market plunge + flow" rule below
# rather than inventing a second number for the same idea.
WEAK_MARKET_THRESHOLD_PCT = -1.5
STOCK_HOLDING_UP_PCT = 1.0  # "종목 +1% 이상"

WEAK_MARKET_STRONG_RESILIENCE_POINTS = 2.0
WEAK_MARKET_MILD_RESILIENCE_POINTS = 1.0
MARKET_PLUNGE_WITH_FLOW_POINTS = 2.0
FLOW_NOT_PERSISTENT_PENALTY = -3.0


class InteractionLabel(str, Enum):
    """Matches this phase's own worked examples (HPSP/삼성전기) - stored
    alongside the numeric score so a later review doesn't have to
    re-derive "why" from the raw numbers."""

    STRONG_RELATIVE_STRENGTH = "STRONG_RELATIVE_STRENGTH"
    WEAK_MARKET_RESILIENT = "WEAK_MARKET_RESILIENT"
    FLOW_NOT_PERSISTENT = "FLOW_NOT_PERSISTENT"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class InteractionScore:
    weak_market_resilience_score: float
    flow_resilience_score: float
    interaction_score: float
    label: InteractionLabel


def _both_net_buying(foreign_net: float, institution_net: float) -> bool:
    """"동반매수" (both investor classes net buying, not just their sum) -
    a stock where foreign selling is fully offset by institutional buying
    isn't the same signal as both genuinely buying, even though a
    sum-only check would score them the same."""
    return foreign_net > 0 and institution_net > 0


def compute_interaction_score(
    benchmark_return_pct: float,
    stock_return_pct: float,
    foreign_net_today: float,
    institution_net_today: float,
    *,
    foreign_net_prev_day: float | None = None,
    institution_net_prev_day: float | None = None,
) -> InteractionScore:
    """`*_pct` values are plain percentages (e.g. `-1.5` for -1.5%), matching
    how this project already prints regime/gap percentages elsewhere
    (`entry_confirmation.py`'s `gap_pct`). `foreign_net_prev_day`/
    `institution_net_prev_day` are optional - the FLOW_NOT_PERSISTENT rule
    (P34-2 below) only fires when a caller actually has yesterday's flow to
    compare against; omitted (the default) rather than defaulted to 0.0,
    since a missing prior day and a genuine prior-day net-sell are not the
    same thing.

    ## Weak Market Resilience (a stock holding up while the market falls)
    Tiered, not additive - `stock_return_pct >= 1.0` implies
    `stock_return_pct >= 0`, so only the single best-matching tier scores
    (+2, not +2 and +1 stacked):
    - market <= -1.5% and stock >= +1%  -> +2 (label STRONG_RELATIVE_STRENGTH)
    - market <= -1.5% and stock >= 0%   -> +1 (label WEAK_MARKET_RESILIENT)

    ## Flow Resilience (today's institutional flow context)
    - market <= -1.5% and both foreign+institution net buying today -> +2
      (folded into the same STRONG_RELATIVE_STRENGTH label - real
      institutional conviction during a market plunge is the strongest
      version of the same story the price-resilience rule above tells)
    - yesterday both foreign+institution net buying, but today the stock
      underperforms the benchmark (`stock_return_pct < benchmark_return_pct`)
      -> -3 (label FLOW_NOT_PERSISTENT) - yesterday's flow didn't carry
      through, the real pattern behind this phase's 삼성전기 example.
      Only evaluated when both `*_prev_day` values are supplied.
    """
    weak_market_resilience_score = 0.0
    flow_resilience_score = 0.0
    label = InteractionLabel.NEUTRAL

    if benchmark_return_pct <= WEAK_MARKET_THRESHOLD_PCT:
        if stock_return_pct >= STOCK_HOLDING_UP_PCT:
            weak_market_resilience_score = WEAK_MARKET_STRONG_RESILIENCE_POINTS
            label = InteractionLabel.STRONG_RELATIVE_STRENGTH
        elif stock_return_pct >= 0:
            weak_market_resilience_score = WEAK_MARKET_MILD_RESILIENCE_POINTS
            label = InteractionLabel.WEAK_MARKET_RESILIENT

        if _both_net_buying(foreign_net_today, institution_net_today):
            flow_resilience_score += MARKET_PLUNGE_WITH_FLOW_POINTS
            label = InteractionLabel.STRONG_RELATIVE_STRENGTH

    if (
        foreign_net_prev_day is not None
        and institution_net_prev_day is not None
        and _both_net_buying(foreign_net_prev_day, institution_net_prev_day)
        and stock_return_pct < benchmark_return_pct
    ):
        flow_resilience_score += FLOW_NOT_PERSISTENT_PENALTY
        label = InteractionLabel.FLOW_NOT_PERSISTENT

    return InteractionScore(
        weak_market_resilience_score=weak_market_resilience_score,
        flow_resilience_score=flow_resilience_score,
        interaction_score=weak_market_resilience_score + flow_resilience_score,
        label=label,
    )
