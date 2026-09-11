"""Stock feature calculations (P4, extended in P23).

Pure functions over P1 `Candle` series - no I/O, no persistence, so they can
be unit-tested against hand-built or historical fixture data. Later phases
(P6 recommendation engine, P23 scoring engine) compose these into a single
score; this module only computes the individual signals: VWAP, RVOL,
turnover acceleration, opening range, price action (CLV), relative
strength, liquidity (P4), and box compression / OBV / distance-to-high
(P23 - Bollinger width from app/technical/indicators.py rather than a
second implementation).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.domain import Candle
from app.technical.indicators import bollinger_bands


def typical_price(candle: Candle) -> float:
    return (candle.high + candle.low + candle.close) / 3


def vwap_series(candles: list[Candle]) -> list[float]:
    """Cumulative (session) VWAP, one value per candle."""
    values: list[float] = []
    cum_pv = 0.0
    cum_vol = 0.0
    for candle in candles:
        cum_pv += typical_price(candle) * candle.volume
        cum_vol += candle.volume
        values.append(cum_pv / cum_vol if cum_vol else typical_price(candle))
    return values


def vwap(candles: list[Candle]) -> float:
    """Current (latest) session VWAP. Empty input is a caller error, not 0.0."""
    if not candles:
        raise ValueError("vwap() requires at least one candle")
    return vwap_series(candles)[-1]


def relative_volume(current_volume: float, average_volume: float) -> float:
    """RVOL: current volume as a multiple of the historical average.

    `average_volume` should be the average volume over an equivalent prior
    window (e.g. same time-of-day average over the last N sessions) - that
    alignment is the caller's responsibility, this is just the ratio.
    """
    if average_volume <= 0:
        return 0.0
    return current_volume / average_volume


def turnover(candle: Candle) -> float:
    """거래대금: notional value traded in one candle."""
    return candle.close * candle.volume


def turnover_acceleration(candles: list[Candle], window: int = 5) -> float:
    """Relative change in average turnover between two adjacent windows.

    Positive means money flow is accelerating into the name; 0.0 when there
    isn't enough history for two full windows or the prior window had zero
    turnover.
    """
    if len(candles) < 2 * window:
        return 0.0
    turnovers = [turnover(c) for c in candles]
    recent = sum(turnovers[-window:]) / window
    prior = sum(turnovers[-2 * window : -window]) / window
    if prior <= 0:
        return 0.0
    return (recent - prior) / prior


@dataclass
class OpeningRange:
    high: float
    low: float


def opening_range(candles: list[Candle], bars: int) -> OpeningRange:
    """High/low of the first `bars` candles of the session."""
    if not candles:
        raise ValueError("opening_range() requires at least one candle")
    window = candles[: max(bars, 1)]
    return OpeningRange(high=max(c.high for c in window), low=min(c.low for c in window))


def close_location_value(candle: Candle) -> float:
    """CLV: -1.0 (closed at the low) to +1.0 (closed at the high), 0.0 if no range."""
    bar_range = candle.high - candle.low
    if bar_range == 0:
        return 0.0
    return ((candle.close - candle.low) - (candle.high - candle.close)) / bar_range


def relative_strength(stock_candles: list[Candle], benchmark_candles: list[Candle]) -> float:
    """Stock's return over the window minus the benchmark's return over the same window."""
    if len(stock_candles) < 2 or len(benchmark_candles) < 2:
        raise ValueError("relative_strength() requires at least 2 candles for both series")
    stock_return = stock_candles[-1].close / stock_candles[0].close - 1
    benchmark_return = benchmark_candles[-1].close / benchmark_candles[0].close - 1
    return stock_return - benchmark_return


def liquidity_score(candles: list[Candle]) -> float:
    """Average turnover over the window - a simple, honest proxy for tradability.

    Real liquidity also depends on spread and order-book depth, which requires
    live orderbook history this phase doesn't have yet; this is deliberately
    named for what it actually measures rather than overclaiming.
    """
    if not candles:
        return 0.0
    return sum(turnover(c) for c in candles) / len(candles)


def compression_score(candles: list[Candle], window: int = 20, lookback: int = 60) -> float | None:
    """0.0 (wide) to 1.0 (most compressed in `lookback` bars) - the current
    Bollinger Band width's percentile rank against its own trailing
    history, so "compressed" is relative to this stock's own normal
    range rather than an arbitrary absolute threshold (a low-volatility
    penny stock and a high-volatility momentum name don't share one
    cutoff). `None` when there isn't enough history yet, never a
    fabricated value (see app/radar/features.py's module-wide convention
    of returning `None`/raising rather than guessing).
    """
    bands = bollinger_bands(candles, window)
    widths = [
        (b.upper - b.lower) / b.middle if b is not None and b.middle else None for b in bands
    ]
    trailing = [w for w in widths[-lookback:] if w is not None]
    current = widths[-1] if widths else None
    if current is None or not trailing:
        return None
    return sum(1 for w in trailing if w >= current) / len(trailing)


def obv(candles: list[Candle]) -> list[float]:
    """On-Balance Volume: cumulative volume added on an up close, subtracted
    on a down close, unchanged on a flat close. Index-aligned with `candles`
    (`obv(candles)[i]` is OBV as of `candles[i]`), first value always 0.0."""
    values = [0.0]
    for i in range(1, len(candles)):
        if candles[i].close > candles[i - 1].close:
            values.append(values[-1] + candles[i].volume)
        elif candles[i].close < candles[i - 1].close:
            values.append(values[-1] - candles[i].volume)
        else:
            values.append(values[-1])
    return values


def obv_slope(candles: list[Candle], window: int = 10) -> float | None:
    """OBV's change over the last `window` bars, normalized by the window's
    average volume so it's comparable across stocks of very different
    liquidity - a rough "how many typical days' worth of net buying
    pressure accumulated" figure. `None` without enough history."""
    if len(candles) < window + 1:
        return None
    values = obv(candles)
    change = values[-1] - values[-1 - window]
    avg_volume = sum(c.volume for c in candles[-window:]) / window
    if avg_volume <= 0:
        return None
    return change / (avg_volume * window)


def distance_to_high(candles: list[Candle], window: int = 20) -> float | None:
    """Fractional distance of the latest close below the `window`-bar high:
    0.0 = the latest bar's own high/close set (or matched) the window high,
    larger = further below it. Always >= 0 for valid OHLC data, since the
    window includes the latest bar itself and a bar's high can never be
    below its own close - this measures "how close to a fresh high", not
    "has it already broken one" (that distinction needs the bar-by-bar
    state tracking `app/radar/state.py` already does, not a single-bar
    snapshot like this one). `None` without enough history."""
    if len(candles) < window:
        return None
    recent = candles[-window:]
    high = max(c.high for c in recent)
    if high <= 0:
        return None
    return (high - candles[-1].close) / high
