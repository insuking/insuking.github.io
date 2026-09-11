"""Technical indicator ensemble (P10).

Pure functions over a `Candle` series, each returning a value series aligned
1:1 with the input (index i is "the indicator as of candles[i]"). Bars
before there's enough history to compute a value get `None`, never a
fabricated number - callers (ensemble.py) treat `None` as "not enough
history yet", not zero.

These are individual signal ingredients; per docs/MASTER_SPEC.md P10 the
combined ensemble score they feed (ensemble.py) never places an order by
itself - there is no order-placement code anywhere in this codebase yet
(that's P15, gated by the human-approval flow P13/P14 build).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.domain import Candle


def sma(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < window:
            result.append(None)
        else:
            result.append(sum(values[i + 1 - window : i + 1]) / window)
    return result


def stdev(values: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < window:
            result.append(None)
            continue
        chunk = values[i + 1 - window : i + 1]
        mean = sum(chunk) / window
        variance = sum((v - mean) ** 2 for v in chunk) / window
        result.append(variance**0.5)
    return result


def ema_series(values: list[float], window: int) -> list[float | None]:
    """Standard EMA, seeded with an SMA of the first `window` values."""
    result: list[float | None] = [None] * len(values)
    if len(values) < window:
        return result
    multiplier = 2 / (window + 1)
    prev = sum(values[:window]) / window
    result[window - 1] = prev
    for i in range(window, len(values)):
        prev = (values[i] - prev) * multiplier + prev
        result[i] = prev
    return result


@dataclass
class BollingerBand:
    middle: float
    upper: float
    lower: float


def bollinger_bands(
    candles: list[Candle], window: int = 20, num_std: float = 2.0
) -> list[BollingerBand | None]:
    closes = [c.close for c in candles]
    middles = sma(closes, window)
    deviations = stdev(closes, window)
    return [
        None if mid is None or sd is None else BollingerBand(mid, mid + num_std * sd, mid - num_std * sd)
        for mid, sd in zip(middles, deviations)
    ]


def true_range(candles: list[Candle]) -> list[float]:
    ranges = []
    for i, candle in enumerate(candles):
        if i == 0:
            ranges.append(candle.high - candle.low)
        else:
            prev_close = candles[i - 1].close
            ranges.append(
                max(candle.high - candle.low, abs(candle.high - prev_close), abs(candle.low - prev_close))
            )
    return ranges


def atr(candles: list[Candle], window: int = 14) -> list[float | None]:
    """Wilder's smoothed Average True Range."""
    ranges = true_range(candles)
    result: list[float | None] = [None] * len(candles)
    if len(candles) < window:
        return result
    prev = sum(ranges[:window]) / window
    result[window - 1] = prev
    for i in range(window, len(candles)):
        prev = (prev * (window - 1) + ranges[i]) / window
        result[i] = prev
    return result


@dataclass
class KeltnerChannel:
    middle: float
    upper: float
    lower: float


def keltner_channel(
    candles: list[Candle], ema_window: int = 20, atr_window: int = 10, multiplier: float = 2.0
) -> list[KeltnerChannel | None]:
    closes = [c.close for c in candles]
    middles = ema_series(closes, ema_window)
    atrs = atr(candles, atr_window)
    return [
        None if mid is None or a is None else KeltnerChannel(mid, mid + multiplier * a, mid - multiplier * a)
        for mid, a in zip(middles, atrs)
    ]


@dataclass
class MACDValue:
    macd: float
    signal: float
    histogram: float


def macd(
    candles: list[Candle], fast: int = 12, slow: int = 26, signal_window: int = 9
) -> list[MACDValue | None]:
    closes = [c.close for c in candles]
    fast_ema = ema_series(closes, fast)
    slow_ema = ema_series(closes, slow)
    macd_line = [
        None if f is None or s is None else f - s for f, s in zip(fast_ema, slow_ema)
    ]

    result: list[MACDValue | None] = [None] * len(candles)
    valid_start = next((i for i, v in enumerate(macd_line) if v is not None), None)
    if valid_start is None:
        return result

    # Once defined, macd_line stays defined (slow EMA determines valid_start
    # since slow > fast), so this slice is safely all-float for ema_series.
    macd_values: list[float] = [v for v in macd_line[valid_start:] if v is not None]
    signal_series = ema_series(macd_values, signal_window)

    for offset, (macd_value, signal_value) in enumerate(zip(macd_values, signal_series)):
        if signal_value is None:
            continue
        result[valid_start + offset] = MACDValue(
            macd=macd_value, signal=signal_value, histogram=macd_value - signal_value
        )
    return result


def rsi(candles: list[Candle], window: int = 14) -> list[float | None]:
    """Wilder's RSI."""
    closes = [c.close for c in candles]
    result: list[float | None] = [None] * len(candles)
    if len(candles) < window + 1:
        return result

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]

    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    result[window] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(window, len(gains)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window
        result[i + 1] = _rsi_from_averages(avg_gain, avg_loss)

    return result


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    relative_strength = avg_gain / avg_loss
    return 100 - (100 / (1 + relative_strength))


def mfi(candles: list[Candle], window: int = 14) -> list[float | None]:
    """Money Flow Index: volume-weighted RSI analog over typical price."""
    typical_prices = [(c.high + c.low + c.close) / 3 for c in candles]
    raw_money_flow = [tp * c.volume for tp, c in zip(typical_prices, candles)]

    result: list[float | None] = [None] * len(candles)
    if len(candles) < window + 1:
        return result

    for i in range(window, len(candles)):
        positive_flow = 0.0
        negative_flow = 0.0
        for j in range(i - window + 1, i + 1):
            if typical_prices[j] > typical_prices[j - 1]:
                positive_flow += raw_money_flow[j]
            elif typical_prices[j] < typical_prices[j - 1]:
                negative_flow += raw_money_flow[j]
        if negative_flow == 0:
            result[i] = 100.0
        else:
            money_ratio = positive_flow / negative_flow
            result[i] = 100 - (100 / (1 + money_ratio))

    return result


def psar(
    candles: list[Candle], af_start: float = 0.02, af_step: float = 0.02, af_max: float = 0.2
) -> list[float | None]:
    """Wilder's Parabolic SAR.

    Note: PSAR has several slightly different implementation variants across
    platforms (seeding, first-flip handling); this follows the standard
    textbook algorithm. Treat exact values as implementation-specific and
    prefer the structural properties (SAR trails below price in an uptrend,
    above it in a downtrend, and flips sides when price crosses it) for
    anything that depends on it.
    """
    if len(candles) < 2:
        return [None] * len(candles)

    result: list[float | None] = [None] * len(candles)
    uptrend = candles[1].close >= candles[0].close
    af = af_start
    if uptrend:
        sar = candles[0].low
        extreme_point = candles[1].high
    else:
        sar = candles[0].high
        extreme_point = candles[1].low
    result[1] = sar

    for i in range(2, len(candles)):
        prev_sar = sar
        sar = prev_sar + af * (extreme_point - prev_sar)

        if uptrend:
            sar = min(sar, candles[i - 1].low, candles[i - 2].low)
            if candles[i].low < sar:
                uptrend = False
                sar = extreme_point
                extreme_point = candles[i].low
                af = af_start
            elif candles[i].high > extreme_point:
                extreme_point = candles[i].high
                af = min(af + af_step, af_max)
        else:
            sar = max(sar, candles[i - 1].high, candles[i - 2].high)
            if candles[i].high > sar:
                uptrend = True
                sar = extreme_point
                extreme_point = candles[i].high
                af = af_start
            elif candles[i].low < extreme_point:
                extreme_point = candles[i].low
                af = min(af + af_step, af_max)

        result[i] = sar

    return result
