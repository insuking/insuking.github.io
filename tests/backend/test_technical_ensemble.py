from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import Candle
from app.technical.ensemble import MIN_CANDLES, ensemble_score
from app.technical.indicators import macd, rsi
from app.technical.strategies import StrategySignal, breakout_strategy, vwap_strategy

pytestmark = pytest.mark.P10


def _candle(
    close: float,
    high: float | None = None,
    low: float | None = None,
    volume: float = 10,
    minute: int = 0,
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
    return [_candle(c, high=c + 0.5, low=c - 0.5, minute=i) for i, c in enumerate(closes)]


def test_ensemble_score_none_below_min_candles() -> None:
    candles = _candles([100.0 + i for i in range(MIN_CANDLES - 1)])
    assert ensemble_score(candles) is None


def test_ensemble_score_combines_four_equal_weighted_components() -> None:
    closes = [100.0 + (i % 5) + i * 0.3 for i in range(40)]
    candles = _candles(closes)

    result = ensemble_score(candles)
    assert result is not None

    latest_rsi = rsi(candles)[-1]
    latest_macd = macd(candles)[-1]
    latest_vwap_signal = vwap_strategy(candles)[-1]
    latest_breakout_signal = breakout_strategy(candles)[-1]
    assert latest_rsi is not None
    assert latest_macd is not None

    _signal_score = {StrategySignal.LONG: 100.0, StrategySignal.FLAT: 0.0, StrategySignal.SHORT: -100.0}
    expected_components = {
        "rsi": (latest_rsi - 50) * 2,
        "macd": 100.0 if latest_macd.histogram > 0 else (-100.0 if latest_macd.histogram < 0 else 0.0),
        "vwap_strategy": _signal_score[latest_vwap_signal],
        "breakout_strategy": _signal_score[latest_breakout_signal],
    }

    assert result.components == pytest.approx(expected_components)
    assert result.score == pytest.approx(sum(expected_components.values()) / 4)


def test_ensemble_score_is_bounded_within_normalized_range() -> None:
    # A relentless uptrend should push every component toward its bullish
    # extreme, but the average must still stay within [-100, 100].
    closes = [100.0 + i * 2 for i in range(50)]
    candles = _candles(closes)

    result = ensemble_score(candles)
    assert result is not None
    assert -100.0 <= result.score <= 100.0
    for value in result.components.values():
        assert -100.0 <= value <= 100.0
