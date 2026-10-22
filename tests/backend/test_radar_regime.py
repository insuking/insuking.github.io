from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import Candle
from app.radar.regime import MarketRegime, classify_market_regime

pytestmark = pytest.mark.P4


def _daily_candle(close: float, day: int) -> Candle:
    day_start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
    return Candle(
        symbol="KOSPI",
        interval="1d",
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000,
        open_time=day_start,
        close_time=day_start + timedelta(days=1),
    )


def test_risk_on_when_above_rising_moving_average() -> None:
    # Steady uptrend: both "price above MA" and "MA rising" hold.
    closes = [100 + i for i in range(25)]
    candles = [_daily_candle(c, i) for i, c in enumerate(closes)]

    assert classify_market_regime(candles, ma_window=20) == MarketRegime.RISK_ON


def test_risk_off_when_below_falling_moving_average() -> None:
    closes = [200 - i for i in range(25)]
    candles = [_daily_candle(c, i) for i, c in enumerate(closes)]

    assert classify_market_regime(candles, ma_window=20) == MarketRegime.RISK_OFF


def test_neutral_when_insufficient_history() -> None:
    candles = [_daily_candle(100, i) for i in range(5)]
    assert classify_market_regime(candles, ma_window=20) == MarketRegime.NEUTRAL


def test_neutral_when_price_and_trend_disagree() -> None:
    # A one-day pullback: the 5-bar MA is still rising off the earlier
    # uptrend's momentum, but today's close has dipped back under it - the
    # two signals disagree, which must not be forced into RISK_ON/RISK_OFF.
    closes = [100, 102, 104, 106, 108, 103]
    candles = [_daily_candle(c, i) for i, c in enumerate(closes)]

    assert classify_market_regime(candles, ma_window=5) == MarketRegime.NEUTRAL
