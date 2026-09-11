from datetime import UTC, datetime, timedelta

import pytest

from app.guardian.trailing import trailing_stop_price
from app.models.domain import Candle
from app.technical.indicators import atr

pytestmark = pytest.mark.P16


def _candle(close: float, minute: int) -> Candle:
    start = datetime(2026, 1, 5, tzinfo=UTC) + timedelta(minutes=minute)
    return Candle(
        symbol="TEST",
        interval="1m",
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=10,
        open_time=start,
        close_time=start + timedelta(minutes=1),
    )


def _candles(count: int) -> list[Candle]:
    return [_candle(100.0 + i, minute=i) for i in range(count)]


def test_trailing_stop_tightens_when_candidate_is_higher() -> None:
    candles = _candles(14)
    latest_atr = atr(candles, window=14)[-1]
    assert latest_atr is not None
    expected_candidate = candles[-1].close - 2.0 * latest_atr

    result = trailing_stop_price(candles, current_stop=50.0)

    assert expected_candidate > 50.0  # sanity: this scenario should actually tighten
    assert result == pytest.approx(expected_candidate)


def test_trailing_stop_never_loosens_below_current_stop() -> None:
    candles = _candles(14)
    latest_atr = atr(candles, window=14)[-1]
    assert latest_atr is not None
    candidate = candles[-1].close - 2.0 * latest_atr

    result = trailing_stop_price(candles, current_stop=candidate + 100.0)

    assert result == pytest.approx(candidate + 100.0)


def test_trailing_stop_unchanged_without_enough_history() -> None:
    candles = _candles(5)
    result = trailing_stop_price(candles, current_stop=42.0)
    assert result == 42.0


def test_trailing_stop_respects_custom_multiplier_and_window() -> None:
    candles = _candles(20)
    latest_atr = atr(candles, window=10)[-1]
    assert latest_atr is not None
    expected_candidate = candles[-1].close - 3.0 * latest_atr

    result = trailing_stop_price(candles, current_stop=0.0, atr_multiplier=3.0, atr_window=10)

    assert result == pytest.approx(expected_candidate)
