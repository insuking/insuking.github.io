from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import Candle, OrderBook, OrderBookLevel, OrderSide
from app.radar.crypto_features import (
    classify_btc_regime,
    detect_feed_anomaly,
    estimate_slippage,
    orderbook_imbalance,
    pump_risk_score,
    realized_volatility,
    relative_strength_vs_btc,
    spread,
)
from app.radar.regime import MarketRegime

pytestmark = pytest.mark.P8


def _candle(close: float, volume: float, minute: int = 0, open_: float | None = None) -> Candle:
    start = datetime(2026, 1, 5, minute=0, tzinfo=UTC) + timedelta(minutes=minute)
    o = open_ if open_ is not None else close
    high = max(o, close)
    low = min(o, close)
    return Candle(
        symbol="KRW-BTC",
        interval="1m",
        open=o,
        high=high,
        low=low,
        close=close,
        volume=volume,
        open_time=start,
        close_time=start + timedelta(minutes=1),
    )


def _flat_series(price: float, volume: float, count: int) -> list[Candle]:
    return [_candle(price, volume, minute=i) for i in range(count)]


def _book(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> OrderBook:
    now = datetime(2026, 1, 5, tzinfo=UTC)
    return OrderBook(
        symbol="KRW-BTC",
        bids=[OrderBookLevel(price=p, quantity=q) for p, q in bids],
        asks=[OrderBookLevel(price=p, quantity=q) for p, q in asks],
        exchange_ts=now,
        received_ts=now,
    )


# --- realized_volatility -----------------------------------------------


def test_realized_volatility_zero_for_flat_series() -> None:
    assert realized_volatility(_flat_series(100, 10, 5)) == 0.0


def test_realized_volatility_matches_hand_calculation() -> None:
    candles = [_candle(100, 1, 0), _candle(110, 1, 1), _candle(99, 1, 2)]
    # returns: +0.10, -0.1 (110->99 = -0.1)
    vol = realized_volatility(candles)
    mean = (0.10 + (-0.1)) / 2
    expected_var = ((0.10 - mean) ** 2 + (-0.1 - mean) ** 2) / 2
    assert vol == pytest.approx(expected_var**0.5)


def test_realized_volatility_needs_two_candles() -> None:
    assert realized_volatility([_candle(100, 1)]) == 0.0
    assert realized_volatility([]) == 0.0


# --- spread / orderbook_imbalance ---------------------------------------


def test_spread_basic() -> None:
    book = _book(bids=[(100, 1)], asks=[(102, 1)])
    assert spread(book) == pytest.approx(2 / 101)


def test_spread_empty_book_is_zero() -> None:
    assert spread(_book(bids=[], asks=[(102, 1)])) == 0.0
    assert spread(_book(bids=[(100, 1)], asks=[])) == 0.0


def test_orderbook_imbalance_buy_heavy() -> None:
    book = _book(bids=[(100, 8)], asks=[(102, 2)])
    assert orderbook_imbalance(book) == pytest.approx((8 - 2) / 10)


def test_orderbook_imbalance_sell_heavy() -> None:
    book = _book(bids=[(100, 1)], asks=[(102, 9)])
    assert orderbook_imbalance(book) == pytest.approx((1 - 9) / 10)


def test_orderbook_imbalance_empty_book_is_zero() -> None:
    assert orderbook_imbalance(_book(bids=[], asks=[])) == 0.0


# --- estimate_slippage ---------------------------------------------------


def test_estimate_slippage_within_top_level_is_zero() -> None:
    book = _book(bids=[(100, 5)], asks=[(102, 5)])
    assert estimate_slippage(book, OrderSide.BUY, 3) == pytest.approx(0.0)


def test_estimate_slippage_walks_multiple_levels() -> None:
    book = _book(bids=[], asks=[(100, 1), (101, 1), (102, 1)])
    # Buying 2.5: 1 @ 100, 1 @ 101, 0.5 @ 102 -> avg = (100+101+51)/2.5 = 100.8
    slip = estimate_slippage(book, OrderSide.BUY, 2.5)
    avg_price = (100 * 1 + 101 * 1 + 102 * 0.5) / 2.5
    assert slip == pytest.approx(abs(avg_price - 100) / 100)


def test_estimate_slippage_sell_side_uses_bids() -> None:
    book = _book(bids=[(100, 1), (99, 1)], asks=[(101, 5)])
    slip = estimate_slippage(book, OrderSide.SELL, 1.5)
    avg_price = (100 * 1 + 99 * 0.5) / 1.5
    assert slip == pytest.approx(abs(avg_price - 100) / 100)


def test_estimate_slippage_book_too_thin_returns_zero() -> None:
    book = _book(bids=[], asks=[(100, 1)])
    assert estimate_slippage(book, OrderSide.BUY, 5) == 0.0


def test_estimate_slippage_non_positive_quantity_returns_zero() -> None:
    book = _book(bids=[(100, 1)], asks=[(101, 1)])
    assert estimate_slippage(book, OrderSide.BUY, 0) == 0.0
    assert estimate_slippage(book, OrderSide.BUY, -1) == 0.0


# --- pump / crash fixtures -------------------------------------------------


def test_pump_risk_score_is_low_for_ordinary_market() -> None:
    candles = _flat_series(100, 10, 25)
    assert pump_risk_score(candles) < 10.0


def test_pump_risk_score_is_high_for_pump_fixture() -> None:
    """Rapid run-up + volume spike + volatility spike, in that combination, is a pump."""
    baseline = _flat_series(100, 10, 15)
    pump_window = [_candle(100 + i * 8, 100, minute=15 + i) for i in range(10)]  # 100 -> 172
    candles = baseline + pump_window

    score = pump_risk_score(candles, lookback=10)

    assert score > 70.0


def test_pump_risk_score_is_low_for_btc_crash_fixture() -> None:
    """A crash has heavy volume and volatility too, but price falls - not a pump."""
    baseline = _flat_series(30000, 50, 15)
    crash_window = [_candle(30000 - i * 1500, 250, minute=15 + i) for i in range(10)]  # -50%
    candles = baseline + crash_window

    pump_score = pump_risk_score(candles, lookback=10)
    pump_fixture_score = pump_risk_score(
        baseline + [_candle(30000 + i * 2400, 250, minute=15 + i) for i in range(10)], lookback=10
    )

    assert pump_score < 50.0
    assert pump_score < pump_fixture_score


def test_pump_risk_score_needs_enough_history() -> None:
    assert pump_risk_score(_flat_series(100, 10, 3), lookback=10) == 0.0


# --- feed anomaly fixture ----------------------------------------------


def test_detect_feed_anomaly_false_for_clean_series() -> None:
    candles = [_candle(100, 10, 0), _candle(101, 10, 1), _candle(99, 10, 2)]
    assert detect_feed_anomaly(candles) is False


def test_detect_feed_anomaly_true_for_bad_print_fixture() -> None:
    """A single fat-finger tick (e.g. an extra zero) must be flagged, not silently averaged in."""
    candles = [_candle(100, 10, 0), _candle(101, 10, 1), _candle(1010, 10, 2)]
    assert detect_feed_anomaly(candles) is True


def test_detect_feed_anomaly_respects_custom_threshold() -> None:
    candles = [_candle(100, 10, 0), _candle(130, 10, 1)]  # +30%
    assert detect_feed_anomaly(candles, max_single_bar_move=0.5) is False
    assert detect_feed_anomaly(candles, max_single_bar_move=0.2) is True


def test_detect_feed_anomaly_needs_two_candles() -> None:
    assert detect_feed_anomaly([_candle(100, 10)]) is False


# --- reuse sanity (full behavior already covered in test_radar_features.py /
# test_radar_regime.py - this just proves the crypto-flavored re-exports work) --


def test_classify_btc_regime_reuses_stock_regime_classifier() -> None:
    rising = [_candle(30000 + i * 100, 10, minute=i) for i in range(25)]
    assert classify_btc_regime(rising, ma_window=20) == MarketRegime.RISK_ON


def test_relative_strength_vs_btc_reuses_stock_relative_strength() -> None:
    alt = [_candle(100, 1, 0), _candle(110, 1, 1)]
    btc = [_candle(30000, 1, 0), _candle(30300, 1, 1)]
    assert relative_strength_vs_btc(alt, btc) == pytest.approx(0.10 - 0.01)
