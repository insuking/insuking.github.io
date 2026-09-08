"""PRE-BREAKOUT scoring engine (P23).

Weighted 0-100 composite over the price/volume-based signals this phase
can honestly compute today, from the spec's own 100-point table:

    가격압축(14) 거래량초기증가(12) 거래대금증가(8) 20일고점접근(8)
    ATR구조(6) OBV상승(7) 시장상대강도(10)  = 65 points implemented here

Three categories from that same table - 외국인/기관/프로그램 수급 (19pt),
업종 상대강도 (8pt), Catalyst (8pt) = 35pt - need data sources this project
does not have yet (a KIS investor-flow feed, a sector index feed, a DART/
news collector) and are deliberately deferred to P24/P25 rather than faked
here. `SCORE_MAX_AVAILABLE` (65.0) is the honest denominator until those
land - never treat a 65/65 score from this module as 100/100, and never
report `total_score` without also reporting `max_available` next to it.

No new feature-calculation logic lives here beyond what P23 specifically
needed (see app/radar/features.py's `compression_score`/`obv_slope`/
`distance_to_high` and app/technical/indicators.py's `atr`) - this module
is only the weighting/composition layer, the same shape as P6's
`score_recommendation()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.domain import Candle
from app.radar.features import (
    compression_score,
    distance_to_high,
    obv_slope,
    relative_strength,
    relative_volume,
    turnover_acceleration,
)
from app.technical.indicators import atr

MODEL_VERSION = "prebreakout-v1-p23"

DEFAULT_VOLUME_RECENT_WINDOW = 5
DEFAULT_VOLUME_BASELINE_WINDOW = 20
DEFAULT_HIGH_WINDOW = 20
DEFAULT_ATR_WINDOW = 14
DEFAULT_ATR_LOOKBACK = 60
DEFAULT_OBV_WINDOW = 10
DEFAULT_COMPRESSION_WINDOW = 20
DEFAULT_COMPRESSION_LOOKBACK = 60

# Ideal "early volume increase" band per the spec: 1.3x~3x average - too
# far below isn't yet a signal, too far above is already a breakout in
# progress (a live mover, not a pre-breakout candidate).
_VOLUME_IDEAL_LOW = 1.3
_VOLUME_IDEAL_HIGH = 3.0

# 0~5% below the window high is the spec's "approaching, not chasing"
# band; effectively 0 by 20% away.
_DISTANCE_IDEAL_MAX = 0.05
_DISTANCE_ZERO_AT = 0.20


@dataclass(frozen=True)
class PreBreakoutWeights:
    """A named, versionable weight set - `model_weight_versions` (P23 DB
    schema) persists these so a later weekly-learning phase can propose a
    new version rather than mutating this default in place."""

    compression: float = 14.0
    volume_increase: float = 12.0
    value_increase: float = 8.0
    distance_to_high: float = 8.0
    atr_structure: float = 6.0
    obv_rising: float = 7.0
    market_relative_strength: float = 10.0

    @property
    def total(self) -> float:
        return (
            self.compression
            + self.volume_increase
            + self.value_increase
            + self.distance_to_high
            + self.atr_structure
            + self.obv_rising
            + self.market_relative_strength
        )


DEFAULT_WEIGHTS = PreBreakoutWeights()
SCORE_MAX_AVAILABLE = DEFAULT_WEIGHTS.total  # 65.0
SCORE_MAX_FULL_SPEC = 100.0  # once P24 (flow, 19pt) + P25 (catalyst, 8pt) + sector RS (8pt) land


@dataclass
class ScoreFactor:
    factor: str
    points: float
    detail: str


@dataclass
class PreBreakoutScore:
    symbol: str
    total_score: float
    max_available: float
    positive: list[ScoreFactor] = field(default_factory=list)
    negative: list[ScoreFactor] = field(default_factory=list)
    model_version: str = MODEL_VERSION


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _percentile_rank_of_last(values: list[float | None], lookback: int) -> float | None:
    """1.0 = the last value is the SMALLEST in the trailing `lookback`
    window (most compressed/contracted), 0.0 = the largest. Shared shape
    between `compression_score` (Bollinger width) and this module's ATR
    scoring (ATR%) - both ask "is this measure unusually tight for this
    stock right now", just over a different underlying series."""
    trailing = [v for v in values[-lookback:] if v is not None]
    current = values[-1] if values else None
    if current is None or not trailing:
        return None
    return sum(1 for v in trailing if v >= current) / len(trailing)


def score_prebreakout(
    symbol: str,
    candles: list[Candle],
    benchmark_candles: list[Candle],
    weights: PreBreakoutWeights = DEFAULT_WEIGHTS,
) -> PreBreakoutScore | None:
    """`candles`/`benchmark_candles`: chronological daily bars, long enough
    for a 20-bar Bollinger/high window and a 60-bar ATR lookback (~65+
    bars is a safe minimum). Returns `None` rather than a partial or
    fabricated score when there isn't enough history yet - the same
    "never guess" gating `build_recommendation()` (P6) already uses.
    """
    min_bars = DEFAULT_ATR_LOOKBACK + DEFAULT_ATR_WINDOW
    if len(candles) < min_bars or len(benchmark_candles) < 2:
        return None

    positive: list[ScoreFactor] = []
    negative: list[ScoreFactor] = []
    total = 0.0

    # 가격압축 (box compression)
    compression = compression_score(candles, window=DEFAULT_COMPRESSION_WINDOW, lookback=DEFAULT_COMPRESSION_LOOKBACK)
    if compression is not None:
        points = compression * weights.compression
        total += points
        if compression >= 0.7:
            positive.append(
                ScoreFactor("box_compression", points, f"변동폭이 최근 구간 중 상위 {compression * 100:.0f}%로 압축")
            )

    # 거래량 초기 증가
    recent = candles[-DEFAULT_VOLUME_RECENT_WINDOW:]
    baseline = candles[-DEFAULT_VOLUME_BASELINE_WINDOW : -DEFAULT_VOLUME_RECENT_WINDOW]
    recent_avg_volume = sum(c.volume for c in recent) / len(recent)
    baseline_avg_volume = sum(c.volume for c in baseline) / len(baseline) if baseline else 0.0
    rvol = relative_volume(recent_avg_volume, baseline_avg_volume)
    if rvol > 0:
        if rvol < _VOLUME_IDEAL_LOW:
            volume_fraction = _clamp01((rvol - 1.0) / (_VOLUME_IDEAL_LOW - 1.0)) if _VOLUME_IDEAL_LOW > 1.0 else 0.0
        elif rvol <= _VOLUME_IDEAL_HIGH:
            volume_fraction = 1.0
        else:
            volume_fraction = 0.0  # already elevated well past "early increase" - informational only, no bonus
        points = volume_fraction * weights.volume_increase
        total += points
        if volume_fraction >= 0.7:
            positive.append(ScoreFactor("volume_increase", points, f"최근 거래량이 평균 대비 {rvol:.1f}배"))
        elif rvol > _VOLUME_IDEAL_HIGH:
            negative.append(
                ScoreFactor("volume_already_extreme", 0.0, f"거래량이 이미 {rvol:.1f}배로 과열 - 사전돌파 구간 아님")
            )

    # 거래대금 증가
    value_accel = turnover_acceleration(candles, window=DEFAULT_VOLUME_RECENT_WINDOW)
    value_fraction = _clamp01(value_accel / 0.5) if value_accel > 0 else 0.0
    points = value_fraction * weights.value_increase
    total += points
    if value_fraction >= 0.7:
        positive.append(ScoreFactor("value_increase", points, f"거래대금 {value_accel * 100:.0f}% 증가"))

    # 20일 고점 접근 (distance_to_high() is always >= 0 for valid OHLC - see
    # its docstring - so there is no separate "already broken out" branch
    # here; a distance near 0 is scored as "at/near the high", which the
    # ideal band below already treats as the strongest case).
    distance = distance_to_high(candles, window=DEFAULT_HIGH_WINDOW)
    if distance is not None:
        if distance <= _DISTANCE_IDEAL_MAX:
            distance_fraction = 1.0
        else:
            distance_fraction = _clamp01(1.0 - (distance - _DISTANCE_IDEAL_MAX) / (_DISTANCE_ZERO_AT - _DISTANCE_IDEAL_MAX))
        points = distance_fraction * weights.distance_to_high
        total += points
        if distance_fraction >= 0.7:
            positive.append(ScoreFactor("distance_to_high", points, f"20일 고점까지 {distance * 100:.1f}% 남음"))

    # ATR 구조 (contracting volatility, same percentile-rank shape as compression)
    atr_values = atr(candles, window=DEFAULT_ATR_WINDOW)
    atr_pct_values = [
        (a / c.close) if a is not None and c.close else None for a, c in zip(atr_values, candles, strict=True)
    ]
    atr_compression = _percentile_rank_of_last(atr_pct_values, DEFAULT_ATR_LOOKBACK)
    if atr_compression is not None:
        points = atr_compression * weights.atr_structure
        total += points
        if atr_compression >= 0.7:
            positive.append(ScoreFactor("atr_structure", points, "ATR 변동성이 최근 구간 대비 축소"))

    # OBV 상승
    obv_slope_value = obv_slope(candles, window=DEFAULT_OBV_WINDOW)
    if obv_slope_value is not None:
        obv_fraction = _clamp01(obv_slope_value) if obv_slope_value > 0 else 0.0
        points = obv_fraction * weights.obv_rising
        total += points
        if obv_fraction >= 0.7:
            positive.append(ScoreFactor("obv_rising", points, "OBV(누적거래량)가 우상향"))
        elif obv_slope_value < -0.3:
            negative.append(ScoreFactor("obv_falling", 0.0, "OBV(누적거래량)가 하락 중"))

    # 시장 상대강도 (vs the given benchmark - KOSPI/KOSDAQ index candles)
    rs = relative_strength(candles, benchmark_candles)
    rs_fraction = _clamp01(rs / 0.10) if rs > 0 else 0.0
    points = rs_fraction * weights.market_relative_strength
    total += points
    if rs_fraction >= 0.7:
        positive.append(ScoreFactor("market_relative_strength", points, f"벤치마크 대비 {rs * 100:.1f}%p 초과 수익"))
    elif rs < -0.03:
        negative.append(ScoreFactor("market_relative_weakness", 0.0, f"벤치마크 대비 {rs * 100:.1f}%p 저조"))

    return PreBreakoutScore(
        symbol=symbol,
        total_score=total,
        max_available=weights.total,
        positive=positive,
        negative=negative,
    )
