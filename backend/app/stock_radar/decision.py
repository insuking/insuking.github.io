"""P36: No-Trade Decision Engine + Dynamic Candidate Threshold.

Before this phase, the stock radar pipeline always tried to find *some*
candidate - a quiet or hostile market just meant a lower top score, not a
different kind of day. This phase makes "no good candidate today" a
first-class, correctly-labeled outcome (`NO_TRADE_DAY`) instead of an
absence the rest of the system has to infer, and raises the score bar
required to pass at all as the market gets worse (`dynamic_minimum_score`)
rather than using one fixed cutoff regardless of regime.

Two levels, matching the spec's own two-level framing:
- `decide_entry_state()`: one symbol's final call (STRONG_BUY/BUY/WATCH/
  NO_BUY) from its score, the P35 heat gate, and how many of the entry
  filters it passed.
- `decide_daily_state()`: the day's overall call, derived from the best
  symbol's own `decide_entry_state()` result - `NO_TRADE_DAY` exactly when
  nothing on the list reached at least BUY.

**Honest scope limit**: the request this phase implements gives five
regime tiers (STRONG_RISK_ON/RISK_ON/NEUTRAL/RISK_OFF/STRONG_RISK_OFF)
with five different score thresholds. `app/radar/regime.py`'s
`MarketRegime` only has three levels (RISK_ON/RISK_OFF/NEUTRAL, a
level+slope classifier - see its own docstring) and is shared by both the
crypto and stock radars across many call sites; widening it to five
magnitude-aware tiers is a real, separate piece of work with no specified
"how strong is STRONG" cutoff to build from, not something to guess at
here. `dynamic_minimum_score()` below uses three of the five requested
thresholds (80/82/85 for RISK_ON/NEUTRAL/RISK_OFF) against the existing
three-level classifier - still strictly "worse regime, higher bar",
just without the STRONG_* distinction yet.

The exact BUY/WATCH boundary (how many of the 5 entry filters must pass,
what heat level still allows a BUY) is this project's own reasonable
reading of the spec's one worked example (5/5 filters + PASS heat ->
STRONG_BUY) - documented per-tier below, not independently specified,
same "tune from real mornings" discipline as the rest of this phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.radar.regime import MarketRegime
from app.stock_radar.overheat import HeatStatus

DEFAULT_ENTRY_FILTERS_TOTAL = 5

_DYNAMIC_MINIMUM_SCORE = {
    MarketRegime.RISK_ON: 80.0,
    MarketRegime.NEUTRAL: 82.0,
    MarketRegime.RISK_OFF: 85.0,
}


class DecisionState(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    WATCH = "WATCH"
    NO_BUY = "NO_BUY"
    NO_TRADE_DAY = "NO_TRADE_DAY"


@dataclass(frozen=True)
class EntryDecision:
    state: DecisionState
    minimum_score: float
    normalized_score: float
    reason: str


def dynamic_minimum_score(regime: MarketRegime) -> float:
    """Minimum normalized (0-100) score required to even be considered,
    given the current market regime - the worse the regime, the higher the
    bar. See this module's own docstring for why only three of the
    request's five regime tiers are implemented."""
    return _DYNAMIC_MINIMUM_SCORE[regime]


def decide_entry_state(
    normalized_score: float,
    regime: MarketRegime,
    heat_status: HeatStatus,
    entry_filters_passed: int,
    entry_filters_total: int = DEFAULT_ENTRY_FILTERS_TOTAL,
) -> EntryDecision:
    """`normalized_score`: the radar score already rescaled to 0-100 (same
    rescaling `app/stock_radar/recommendation.py`'s `build_stock_recommendation()`
    already does - `score.total_score / score.max_available * 100`), so
    this function's thresholds mean the same thing regardless of whether
    institutional-flow data raised a particular score's own ceiling.

    Ordering matters and is deliberate: TOO_LATE is checked first and
    unconditionally blocks a BUY, however good the score - "removed from
    new-entry recommendation" per this phase's own spec, not merely
    downgraded a tier. The minimum-score gate is checked next; only a
    candidate that clears both goes on to the filter-count tiers.
    """
    minimum_score = dynamic_minimum_score(regime)

    if heat_status == HeatStatus.TOO_LATE:
        return EntryDecision(
            DecisionState.NO_BUY, minimum_score, normalized_score, "TOO_LATE - 이미 과열되어 신규 진입 대상에서 제외"
        )

    if normalized_score < minimum_score:
        return EntryDecision(
            DecisionState.NO_BUY,
            minimum_score,
            normalized_score,
            f"점수 {normalized_score:.1f}이 현재 시장 국면({regime.value}) 최소 기준 {minimum_score:.0f} 미달",
        )

    if entry_filters_passed >= entry_filters_total and heat_status in (HeatStatus.NORMAL, HeatStatus.WARM, HeatStatus.HOT):
        return EntryDecision(
            DecisionState.STRONG_BUY, minimum_score, normalized_score, f"진입필터 {entry_filters_passed}/{entry_filters_total} 전부 통과"
        )

    if entry_filters_passed >= entry_filters_total - 1 and heat_status != HeatStatus.VERY_HOT:
        return EntryDecision(
            DecisionState.BUY, minimum_score, normalized_score, f"진입필터 {entry_filters_passed}/{entry_filters_total} 통과"
        )

    return EntryDecision(
        DecisionState.WATCH,
        minimum_score,
        normalized_score,
        f"점수는 기준을 넘었으나 진입필터 {entry_filters_passed}/{entry_filters_total}만 통과 - 추가 확인 필요",
    )


def decide_daily_state(best_entry_decision: EntryDecision | None) -> DecisionState:
    """The day's overall call: `NO_TRADE_DAY` exactly when nothing scanned
    today reached at least BUY - "좋은 종목이 없으면 아무것도 사지 않는 것"
    is a normal, successful outcome, not an error, so this is a plain
    enum value the caller can display directly, never a `None`/empty-list
    special case the UI has to interpret on its own.
    """
    if best_entry_decision is None:
        return DecisionState.NO_TRADE_DAY
    if best_entry_decision.state in (DecisionState.WATCH, DecisionState.NO_BUY):
        return DecisionState.NO_TRADE_DAY
    return best_entry_decision.state
