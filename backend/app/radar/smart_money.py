"""Smart-money footprint signals (P11).

Pure functions over a `Candle` series, same style and constraints as
`app.radar.features` (P4) and `app.radar.crypto_features` (P8): no I/O, no
persistence, fully unit-testable against hand-built fixtures.

Per docs/MASTER_SPEC.md P11 ("observable signals only... no unsupported
manipulation claims"), every function here describes a statistical pattern
in price/volume that is *consistent with* institutional accumulation or
distribution - it is never presented as proof that any specific actor did
anything. None of this codebase's data sources (KIS/Toss/Upbit, see
P3/P5/P7) expose real order-flow attribution (who traded), so "smart money"
here means "what a large, patient participant's footprint would look like
in the tape that is actually available" - not an identified trader.
"""

from __future__ import annotations

from app.models.domain import Candle
from app.radar.features import close_location_value


def absorption_score(candles: list[Candle], window: int = 20) -> float | None:
    """0-100: unusually high volume paired with an unusually small price range.

    A large order absorbed by a level without moving price is a classic
    accumulation/distribution footprint. Compares the latest bar's volume
    and range against the average of the preceding `window` bars (the
    latest bar itself is excluded from the baseline so it can't skew its
    own comparison). `None` when there isn't a full baseline window yet.
    """
    if len(candles) < window + 1:
        return None

    baseline = candles[-(window + 1) : -1]
    latest = candles[-1]

    baseline_avg_volume = sum(c.volume for c in baseline) / window
    baseline_avg_range = sum(c.high - c.low for c in baseline) / window

    relative_volume = latest.volume / baseline_avg_volume if baseline_avg_volume > 0 else 1.0
    latest_range = latest.high - latest.low
    relative_range = latest_range / baseline_avg_range if baseline_avg_range > 0 else 1.0

    volume_component = max(0.0, min((relative_volume - 1.0) * 40.0, 60.0))
    range_component = max(0.0, min((1.0 - relative_range) * 40.0, 40.0))
    return max(0.0, min(100.0, volume_component + range_component))


def support_defense_count(candles: list[Candle], level: float, tolerance: float = 0.01) -> int:
    """Count of bars whose low dipped within `tolerance` below `level` but
    closed back above it - each one a successful defense of that support
    level. A count, not a claim about who was buying there.
    """
    if level <= 0:
        return 0
    threshold = level * (1 - tolerance)
    return sum(1 for c in candles if threshold <= c.low <= level and c.close > level)


def is_low_volume_pullback(candles: list[Candle], pullback_bars: int = 3, lookback_bars: int = 5) -> bool:
    """True if the trailing `pullback_bars` are a strictly declining pullback
    from an up-move, and that pullback traded on lower average volume than
    the `lookback_bars` up-move that preceded it - sellers weren't
    aggressive, which is a healthier pullback than one on expanding volume.
    """
    if len(candles) < pullback_bars + lookback_bars:
        return False

    pullback = candles[-pullback_bars:]
    prior = candles[-(pullback_bars + lookback_bars) : -pullback_bars]

    is_declining = all(pullback[i].close < pullback[i - 1].close for i in range(1, len(pullback)))
    is_pullback_from_uptrend = pullback[0].close < prior[-1].close
    if not (is_declining and is_pullback_from_uptrend):
        return False

    pullback_avg_volume = sum(c.volume for c in pullback) / len(pullback)
    prior_avg_volume = sum(c.volume for c in prior) / len(prior)
    return pullback_avg_volume < prior_avg_volume


def buy_aggression_ratio(candles: list[Candle], window: int = 10) -> float:
    """Volume-weighted average close-location-value over the trailing window.

    In [-1, 1]. This codebase's `Candle` series has no tick-level
    buy/sell-initiated trade tagging (see module docstring), so this is a
    bar-level proxy: bars that close near their highs on heavier volume
    pull the average up, which is what aggressive buying against offers
    looks like in OHLCV data even without trade-side attribution.
    """
    if not candles:
        return 0.0
    recent = candles[-window:] if len(candles) >= window else candles
    total_volume = sum(c.volume for c in recent)
    if total_volume <= 0:
        return 0.0
    return sum(close_location_value(c) * c.volume for c in recent) / total_volume


def volume_compression_score(
    candles: list[Candle], short_window: int = 5, long_window: int = 20
) -> float | None:
    """0.0-1.0: how much volume and range have contracted recently vs. a
    longer baseline - the "coiling spring" pattern often seen before a
    breakout. 1.0 means the most recent `short_window` bars traded far
    quieter and tighter than the `long_window` baseline that precedes them;
    0.0 means no contraction (or expansion). `None` without a full
    `long_window` of history.
    """
    if len(candles) < long_window:
        return None
    if short_window >= long_window:
        raise ValueError("short_window must be smaller than long_window")

    baseline = candles[-long_window:-short_window]
    recent = candles[-short_window:]
    if not baseline:
        return None

    baseline_avg_volume = sum(c.volume for c in baseline) / len(baseline)
    recent_avg_volume = sum(c.volume for c in recent) / len(recent)
    baseline_avg_range = sum(c.high - c.low for c in baseline) / len(baseline)
    recent_avg_range = sum(c.high - c.low for c in recent) / len(recent)

    if baseline_avg_volume <= 0 or baseline_avg_range <= 0:
        return 0.0

    volume_ratio = recent_avg_volume / baseline_avg_volume
    range_ratio = recent_avg_range / baseline_avg_range
    compression = 1.0 - (volume_ratio + range_ratio) / 2.0
    return max(0.0, min(1.0, compression))
