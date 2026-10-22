"""P35: Overheat / TOO LATE engine.

This project's stock radar exists to catch a PRE-BREAKOUT setup *before*
it moves, not to chase one that already has (see
`app/stock_radar/scoring.py`'s own framing). Nothing before this phase
stopped a high-scoring but already-extended candidate from reaching a
real `Recommendation` - a symbol up 12% in a day with a PRE-BREAKOUT
score of 90 would sail straight through. This module scores how
"heated"/extended a candidate already is and gives
`app/stock_radar/scan.py`'s `build_confirmed_recommendations()` a hard
gate to skip it, however good the underlying score looks.

`heat_score` (0-100) is `100 * max(...)` over each metric's own fraction
of its TOO_LATE threshold, not a hand-tuned weighted sum - the spec this
phase implements gives hard OR thresholds for four of the five inputs
(1-day/2-day/5-day return, distance-from-signal, gap) but no weights for
combining them, so "worst offending metric decides the score" is the
most honest continuous version of those OR conditions: reaching 100% of
any one threshold alone reaches heat_score 100 (solidly inside the
TOO_LATE band), regardless of the others. Volume/ATR extension (asked
for but given no threshold in the spec) are folded in as a smaller,
separately-documented bonus on top, not part of the primary max - see
`_volume_atr_bonus()`.

Every threshold is this project's own conservative reading of the
request, not independently derived - tune from real trading days once
there's evidence to tune from, the same discipline already used
throughout `entry_confirmation.py` and `regime_interaction.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.models.domain import Candle
from app.radar.features import relative_volume
from app.technical.indicators import atr

RETURN_1D_TOO_LATE_PCT = 8.0
RETURN_2D_TOO_LATE_PCT = 15.0
RETURN_5D_TOO_LATE_PCT = 19.0  # spec's own "18-20%" range, midpoint
DISTANCE_FROM_SIGNAL_TOO_LATE_PCT = 8.0
DEFAULT_GAP_ALLOWED_PCT = 3.0  # matches EntryConfirmationThresholds.max_gap_up_pct (entry_confirmation.py)

# Volume/ATR extension: asked for in the spec ("ATR·거래량·Gap까지 포함")
# but given no explicit threshold, unlike the four metrics above - a
# smaller, capped bonus on top of the primary max-fraction score rather
# than a full OR trigger of its own.
_VOLUME_BONUS_START = 2.0  # RVOL above this starts contributing
_VOLUME_BONUS_MAX_POINTS = 10.0
_VOLUME_BONUS_PER_UNIT = 5.0
_ATR_EXTENSION_BONUS_START = 3.0  # "ATR units" above this starts contributing
_ATR_EXTENSION_BONUS_MAX_POINTS = 10.0
_ATR_EXTENSION_BONUS_PER_UNIT = 3.0

_ATR_WINDOW = 14
_RECENT_VOLUME_WINDOW = 5
_BASELINE_VOLUME_WINDOW = 20

HEAT_BAND_BOUNDARIES = {
    "NORMAL": (0.0, 40.0),
    "WARM": (40.0, 60.0),
    "HOT": (60.0, 75.0),
    "VERY_HOT": (75.0, 85.0),
    "TOO_LATE": (85.0, 100.0001),  # inclusive of 100
}


class HeatStatus(str, Enum):
    NORMAL = "NORMAL"
    WARM = "WARM"
    HOT = "HOT"
    VERY_HOT = "VERY_HOT"
    TOO_LATE = "TOO_LATE"


@dataclass(frozen=True)
class HeatScore:
    return_1d_pct: float
    return_2d_pct: float
    return_5d_pct: float
    distance_from_signal_pct: float | None
    gap_pct: float | None
    volume_ratio: float
    atr_extension: float | None
    heat_score: float
    status: HeatStatus


def _status_for(score: float) -> HeatStatus:
    for name, (low, high) in HEAT_BAND_BOUNDARIES.items():
        if low <= score < high:
            return HeatStatus(name)
    return HeatStatus.TOO_LATE  # score > 100 from an extreme input - still TOO_LATE, never out of range


def _pct_return(candles: list[Candle], bars_back: int) -> float:
    if len(candles) <= bars_back:
        return 0.0
    base = candles[-1 - bars_back].close
    if base <= 0:
        return 0.0
    return (candles[-1].close / base - 1) * 100


def _volume_atr_bonus(volume_ratio: float, atr_extension: float | None) -> float:
    bonus = 0.0
    if volume_ratio > _VOLUME_BONUS_START:
        bonus += min(_VOLUME_BONUS_MAX_POINTS, (volume_ratio - _VOLUME_BONUS_START) * _VOLUME_BONUS_PER_UNIT)
    if atr_extension is not None and atr_extension > _ATR_EXTENSION_BONUS_START:
        bonus += min(
            _ATR_EXTENSION_BONUS_MAX_POINTS, (atr_extension - _ATR_EXTENSION_BONUS_START) * _ATR_EXTENSION_BONUS_PER_UNIT
        )
    return bonus


def compute_heat_score(
    candles: list[Candle],
    entry_reference_price: float | None = None,
    gap_pct: float | None = None,
    gap_allowed_pct: float = DEFAULT_GAP_ALLOWED_PCT,
) -> HeatScore | None:
    """`candles`: chronological daily bars, at least `_ATR_WINDOW + 1` of
    them (ATR needs that much; 1d/2d/5d returns degrade to 0.0 - never a
    fabricated large number - when there isn't enough history for that
    specific window, matching `turnover_acceleration()`'s own
    not-enough-history-yet convention). Returns `None`, not a partial
    score, when there isn't even enough history for ATR - the one input
    every other metric here can still degrade gracefully without.

    `entry_reference_price`: the PRE-BREAKOUT score's own `reference_close`
    (`PreBreakoutScore.reference_close`) - literally the price the signal
    was scored from, so "how far above the signal price" reuses data
    already computed rather than inventing a second notion of "signal
    price". `None` (the default) when a caller has no active score to
    compare against - `distance_from_signal_pct` is then `None` too and
    contributes nothing, not zero (a missing reference isn't "at the
    reference").

    `gap_pct`: `EntryConfirmation.gap_pct` (P27) - reused directly rather
    than recomputed. `None` when a caller has no fresh confirmation yet.
    """
    if len(candles) < _ATR_WINDOW + 1:
        return None

    return_1d = _pct_return(candles, 1)
    return_2d = _pct_return(candles, 2)
    return_5d = _pct_return(candles, 5)

    distance_from_signal_pct: float | None = None
    if entry_reference_price is not None and entry_reference_price > 0:
        distance_from_signal_pct = (candles[-1].close / entry_reference_price - 1) * 100

    recent = candles[-_RECENT_VOLUME_WINDOW:]
    baseline = candles[-_BASELINE_VOLUME_WINDOW : -_RECENT_VOLUME_WINDOW] if len(candles) >= _BASELINE_VOLUME_WINDOW else []
    recent_avg_volume = sum(c.volume for c in recent) / len(recent)
    baseline_avg_volume = sum(c.volume for c in baseline) / len(baseline) if baseline else 0.0
    volume_ratio = relative_volume(recent_avg_volume, baseline_avg_volume)

    atr_values = atr(candles, window=_ATR_WINDOW)
    latest_atr = atr_values[-1]
    atr_extension: float | None = None
    atr_extension_signed = 0.0
    five_day_bars_back = min(5, len(candles) - 1)
    if latest_atr is not None and latest_atr > 0 and five_day_bars_back > 0:
        price_change_5d = candles[-1].close - candles[-1 - five_day_bars_back].close
        atr_extension_signed = price_change_5d / latest_atr
        atr_extension = abs(atr_extension_signed)

    fractions = [
        return_1d / RETURN_1D_TOO_LATE_PCT,
        return_2d / RETURN_2D_TOO_LATE_PCT,
        return_5d / RETURN_5D_TOO_LATE_PCT,
    ]
    if distance_from_signal_pct is not None:
        fractions.append(distance_from_signal_pct / DISTANCE_FROM_SIGNAL_TOO_LATE_PCT)
    if gap_pct is not None and gap_allowed_pct > 0:
        fractions.append(gap_pct / gap_allowed_pct)

    # Not clamped to 100 here - an input far beyond its threshold should
    # read as more extreme than one just past it, even though both land in
    # the same TOO_LATE status band via `_status_for()`.
    primary = max([f for f in fractions if f > 0], default=0.0) * 100

    # ATR-extension is a directional "how far has price already moved"
    # measure, so only a genuine upward move contributes - a decline that
    # happens to be many ATRs wide is not "too late to chase a breakout",
    # it's just a decline. Volume is deliberately NOT direction-gated:
    # unusually heavy volume with no net price move yet can itself be a
    # real distribution/exhaustion signal (spec: "ATR·거래량·Gap까지 포함"),
    # not conditional on the price having already run.
    upward_atr_extension = atr_extension if atr_extension_signed > 0 else None
    heat_score = primary + _volume_atr_bonus(volume_ratio, upward_atr_extension)

    return HeatScore(
        return_1d_pct=return_1d,
        return_2d_pct=return_2d,
        return_5d_pct=return_5d,
        distance_from_signal_pct=distance_from_signal_pct,
        gap_pct=gap_pct,
        volume_ratio=volume_ratio,
        atr_extension=atr_extension,
        heat_score=heat_score,
        status=_status_for(heat_score),
    )
