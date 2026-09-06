from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import Candle
from app.technical.backtest import run_backtest
from app.technical.strategies import StrategySignal

pytestmark = pytest.mark.P10


def _candle(close: float, minute: int = 0) -> Candle:
    start = datetime(2026, 1, 5, tzinfo=UTC) + timedelta(minutes=minute)
    return Candle(
        symbol="TEST",
        interval="1m",
        open=close,
        high=close,
        low=close,
        close=close,
        volume=10,
        open_time=start,
        close_time=start + timedelta(minutes=1),
    )


def _candles(closes: list[float]) -> list[Candle]:
    return [_candle(c, minute=i) for i, c in enumerate(closes)]


def test_run_backtest_raises_on_length_mismatch() -> None:
    candles = _candles([100.0, 101.0])
    with pytest.raises(ValueError, match="same length"):
        run_backtest(candles, [StrategySignal.LONG])


def test_run_backtest_no_trades_when_always_flat() -> None:
    candles = _candles([100.0, 101.0, 102.0])
    signals = [StrategySignal.FLAT, StrategySignal.FLAT, StrategySignal.FLAT]
    result = run_backtest(candles, signals)
    assert result.num_trades == 0
    assert result.win_rate == 0.0
    assert result.total_return_pct == 0.0


def test_run_backtest_enters_at_next_bars_open_not_signal_bar_close() -> None:
    # signals[0] is LONG, but entry must execute at candles[1].open, not
    # candles[0].close - proving there's no lookahead.
    closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    candles = _candles(closes)
    signals = [
        StrategySignal.LONG,
        StrategySignal.LONG,
        StrategySignal.LONG,
        StrategySignal.FLAT,
        StrategySignal.FLAT,
    ]
    result = run_backtest(candles, signals)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.direction == StrategySignal.LONG
    assert trade.entry_price == pytest.approx(101.0)  # candles[1].open, not candles[0].close
    assert trade.exit_price == pytest.approx(104.0)  # candles[4].open, when FLAT was observed at signals[3]
    assert trade.return_pct == pytest.approx((104.0 - 101.0) / 101.0)
    assert result.win_rate == pytest.approx(1.0)
    assert result.total_return_pct == pytest.approx((104.0 - 101.0) / 101.0)


def test_run_backtest_short_trade_profits_on_price_decline() -> None:
    closes = [100.0, 99.0, 98.0, 97.0, 96.0]
    candles = _candles(closes)
    signals = [
        StrategySignal.SHORT,
        StrategySignal.SHORT,
        StrategySignal.SHORT,
        StrategySignal.FLAT,
        StrategySignal.FLAT,
    ]
    result = run_backtest(candles, signals)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.direction == StrategySignal.SHORT
    assert trade.entry_price == pytest.approx(99.0)
    assert trade.exit_price == pytest.approx(96.0)
    # SHORT profits when price falls: mult = -1
    assert trade.return_pct == pytest.approx((96.0 - 99.0) / 99.0 * -1)
    assert trade.return_pct > 0


def test_run_backtest_flips_directly_from_long_to_short_without_flat() -> None:
    closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    candles = _candles(closes)
    signals = [
        StrategySignal.LONG,
        StrategySignal.LONG,
        StrategySignal.SHORT,
        StrategySignal.SHORT,
        StrategySignal.SHORT,
    ]
    result = run_backtest(candles, signals)

    # The flip at i=2 closes the LONG leg; the still-open SHORT leg (entered
    # at candles[3].open) is never realized because the series ends first.
    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.direction == StrategySignal.LONG
    assert trade.entry_price == pytest.approx(101.0)
    assert trade.exit_price == pytest.approx(103.0)
    assert trade.return_pct == pytest.approx((103.0 - 101.0) / 101.0)


def test_total_return_pct_compounds_across_multiple_trades() -> None:
    result_trades_win_rate_check = run_backtest(
        _candles([100.0, 110.0, 100.0, 110.0, 100.0]),
        [
            StrategySignal.LONG,
            StrategySignal.FLAT,
            StrategySignal.LONG,
            StrategySignal.FLAT,
            StrategySignal.FLAT,
        ],
    )
    # Trade 1: enter 110 (candles[1].open), exit at candles[2].open=100 -> loss
    # Trade 2: enter 110 (candles[3].open), exit at candles[4].open=100 -> loss
    assert result_trades_win_rate_check.num_trades == 2
    assert result_trades_win_rate_check.win_rate == pytest.approx(0.0)
    expected_total = (1 + (100.0 - 110.0) / 110.0) * (1 + (100.0 - 110.0) / 110.0) - 1
    assert result_trades_win_rate_check.total_return_pct == pytest.approx(expected_total)
