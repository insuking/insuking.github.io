from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import Candle
from app.technical.indicators import (
    atr,
    bollinger_bands,
    ema_series,
    keltner_channel,
    macd,
    mfi,
    psar,
    rsi,
    sma,
    stdev,
    true_range,
)

pytestmark = pytest.mark.P10


def _candle(
    close: float, high: float | None = None, low: float | None = None, volume: float = 10, minute: int = 0
) -> Candle:
    start = datetime(2026, 1, 5, tzinfo=UTC) + timedelta(minutes=minute)
    h = high if high is not None else close
    lo = low if low is not None else close
    return Candle(
        symbol="TEST",
        interval="1m",
        open=close,
        high=h,
        low=lo,
        close=close,
        volume=volume,
        open_time=start,
        close_time=start + timedelta(minutes=1),
    )


def _candles(closes: list[float]) -> list[Candle]:
    return [_candle(c, minute=i) for i, c in enumerate(closes)]


# --- sma / stdev / ema -----------------------------------------------------


def test_sma_basic() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = sma(values, window=3)
    assert result == [None, None, 2.0, 3.0, 4.0]


def test_stdev_basic() -> None:
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    result = stdev(values, window=8)
    # population stdev of this classic example is 2.0
    assert result[-1] == pytest.approx(2.0)


def test_ema_series_seeds_with_sma_then_smooths() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = ema_series(values, window=3)
    assert result[0] is None
    assert result[1] is None
    seed = result[2]
    assert seed is not None
    assert seed == pytest.approx((1 + 2 + 3) / 3)  # seed = SMA
    multiplier = 2 / 4
    expected_3 = (4.0 - seed) * multiplier + seed
    assert result[3] == pytest.approx(expected_3)


# --- bollinger --------------------------------------------------------------


def test_bollinger_bands_matches_sma_and_stdev() -> None:
    closes = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    candles = _candles(closes)
    bands = bollinger_bands(candles, window=8, num_std=2.0)

    assert bands[-1] is not None
    assert bands[-1].middle == pytest.approx(sum(closes) / 8)
    assert bands[-1].upper == pytest.approx(bands[-1].middle + 2.0 * 2.0)
    assert bands[-1].lower == pytest.approx(bands[-1].middle - 2.0 * 2.0)
    assert all(b is None for b in bands[:-1])


# --- true range / atr --------------------------------------------------


def test_true_range_uses_prior_close_when_gap() -> None:
    candles = [
        _candle(close=100, high=102, low=98, minute=0),
        _candle(close=110, high=112, low=109, minute=1),  # gapped up from prior close 100
    ]
    ranges = true_range(candles)
    assert ranges[0] == pytest.approx(102 - 98)
    # true range = max(high-low, |high-prevclose|, |low-prevclose|) = max(3, 12, 9) = 12
    assert ranges[1] == pytest.approx(12)


def test_atr_wilder_smoothing() -> None:
    candles = [_candle(close=100 + i, high=100 + i + 1, low=100 + i - 1, minute=i) for i in range(5)]
    result = atr(candles, window=3)
    tr = true_range(candles)
    seed = sum(tr[:3]) / 3
    assert result[2] == pytest.approx(seed)
    expected_3 = (seed * 2 + tr[3]) / 3
    assert result[3] == pytest.approx(expected_3)


# --- keltner ----------------------------------------------------------


def test_keltner_channel_matches_ema_and_atr() -> None:
    closes = [100.0 + i for i in range(25)]
    candles = [_candle(c, high=c + 1, low=c - 1, minute=i) for i, c in enumerate(closes)]
    channel = keltner_channel(candles, ema_window=20, atr_window=10, multiplier=2.0)

    expected_ema = ema_series(closes, 20)
    expected_atr = atr(candles, 10)
    idx = 20
    channel_value = channel[idx]
    ema_value = expected_ema[idx]
    atr_value = expected_atr[idx]
    assert channel_value is not None
    assert ema_value is not None
    assert atr_value is not None
    assert channel_value.middle == pytest.approx(ema_value)
    assert channel_value.upper == pytest.approx(ema_value + 2.0 * atr_value)
    assert channel_value.lower == pytest.approx(ema_value - 2.0 * atr_value)


# --- macd (independent reference calculation) -------------------------


def _reference_ema(values: list[float], window: int) -> list[float | None]:
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


def test_macd_matches_independent_reference_calculation() -> None:
    closes = [100.0 + (i % 5) + i * 0.3 for i in range(40)]
    candles = _candles(closes)

    result = macd(candles, fast=12, slow=26, signal_window=9)

    fast_ema = _reference_ema(closes, 12)
    slow_ema = _reference_ema(closes, 26)
    macd_line = [f - s if f is not None and s is not None else None for f, s in zip(fast_ema, slow_ema)]
    valid_start = next(i for i, v in enumerate(macd_line) if v is not None)
    macd_values = [v for v in macd_line[valid_start:] if v is not None]
    signal_series = _reference_ema(macd_values, 9)

    last_offset = len(macd_values) - 1
    expected_macd = macd_values[last_offset]
    expected_signal = signal_series[last_offset]
    assert expected_signal is not None

    latest = result[-1]
    assert latest is not None
    assert latest.macd == pytest.approx(expected_macd)
    assert latest.signal == pytest.approx(expected_signal)
    assert latest.histogram == pytest.approx(expected_macd - expected_signal)


def test_macd_none_before_enough_history() -> None:
    candles = _candles([100.0 + i for i in range(10)])
    result = macd(candles, fast=12, slow=26, signal_window=9)
    assert all(v is None for v in result)


# --- rsi (independent reference calculation) ---------------------------


def test_rsi_all_gains_is_100() -> None:
    closes = [100.0 + i for i in range(16)]
    result = rsi(_candles(closes), window=14)
    assert result[14] == pytest.approx(100.0)


def test_rsi_all_losses_is_0() -> None:
    closes = [100.0 - i for i in range(16)]
    result = rsi(_candles(closes), window=14)
    assert result[14] == pytest.approx(0.0)


def test_rsi_matches_independent_reference_calculation() -> None:
    closes = [100, 102, 101, 103, 105, 104, 106, 108, 107, 109, 111, 110, 112, 114, 113]
    result = rsi(_candles([float(c) for c in closes]), window=14)

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, 0) for c in changes]
    losses = [max(-c, 0) for c in changes]
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    expected_rs = avg_gain / avg_loss
    expected_rsi = 100 - 100 / (1 + expected_rs)

    assert result[14] == pytest.approx(expected_rsi)
    assert all(v is None for v in result[:14])


# --- mfi (independent reference calculation) ----------------------------


def test_mfi_matches_independent_reference_calculation() -> None:
    closes = [100, 102, 101, 103, 105, 104, 106, 108, 107, 109, 111, 110, 112, 114, 113]
    candles = _candles([float(c) for c in closes])  # high=low=close, volume=10 for all
    result = mfi(candles, window=14)

    typical_prices = closes  # since high=low=close here
    raw_flow = [tp * 10 for tp in typical_prices]
    positive = sum(raw_flow[j] for j in range(1, 15) if typical_prices[j] > typical_prices[j - 1])
    negative = sum(raw_flow[j] for j in range(1, 15) if typical_prices[j] < typical_prices[j - 1])
    expected_mfi = 100 - 100 / (1 + positive / negative)

    assert result[14] == pytest.approx(expected_mfi)
    assert all(v is None for v in result[:14])


def test_mfi_all_negative_flow_never_divides_by_zero() -> None:
    closes = [100.0 - i for i in range(16)]
    result = mfi(_candles(closes), window=14)
    assert result[14] == pytest.approx(0.0)


# --- psar (structural properties) ---------------------------------------


def test_psar_trails_below_price_in_a_sustained_uptrend() -> None:
    closes = [100.0 + i * 2 for i in range(20)]
    candles = [_candle(c, high=c + 1, low=c - 1, minute=i) for i, c in enumerate(closes)]
    result = psar(candles)

    for i in range(2, len(candles)):
        value = result[i]
        assert value is not None
        assert value <= candles[i].low  # SAR trails price from below while uptrend holds


def test_psar_flips_side_when_price_crosses_it() -> None:
    # A strong uptrend that reverses hard should flip PSAR from below price to above it.
    up = [100.0 + i * 3 for i in range(15)]
    down = [up[-1] - i * 5 for i in range(1, 15)]
    closes = up + down
    candles = [_candle(c, high=c + 1, low=c - 1, minute=i) for i, c in enumerate(closes)]

    result = psar(candles)

    late_values = [v for v in result[-5:] if v is not None]
    assert len(late_values) == 5
    # after the sharp reversal, SAR should have flipped to sit above price
    assert all(v >= candles[-1].high - 200 for v in late_values)  # sanity: same order of magnitude
    last_value = result[-1]
    assert last_value is not None
    assert last_value > candles[-1].close  # now trailing from above, confirming the flip happened
