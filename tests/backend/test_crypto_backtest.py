"""P24: historical replay of the crypto radar recommendation strategy.

Synthetic daily-candle fixtures (not real Upbit data - see
docs/UPBIT_NOTES.md for why this sandbox can't fetch real history) built to
isolate each of `crypto_backtest._check_exit()`'s three outcomes plus the
"never fabricate a trade that shouldn't exist" no-breakout case.

Every breakout fixture below crosses the opening-range high for *two*
consecutive bars before a trade opens: `CryptoRadarStateTracker` requires
`confirm_bars=2` consecutive candidate transitions before committing
STEALTH -> BREAKOUT (see app/radar/crypto_state.py) - unlike
`crypto_scan.py`'s single-shot live scan, a backtest has the bars to let
that hysteresis actually work, and skipping it here would test a shortcut
the real backtest doesn't take.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import Candle
from app.scan.crypto_backtest import backtest_radar_strategy

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(open_: float, high: float, low: float, close: float, volume: float) -> tuple:
    return (open_, high, low, close, volume)


def _opening_range_bars(count: int = 15) -> list[tuple]:
    return [_bar(97.0, 100.0, 95.0, 97.0, 10.0) for _ in range(count)]


def _breakout_confirm_bars() -> list[tuple]:
    """Two consecutive above-the-opening-high closes - the minimum needed
    to actually commit BREAKOUT (see module docstring). The second bar
    (close=108) is also what `build_recommendation()` sizes the trade's
    stop/T2 from, since it's the bar the state commits on."""
    return [
        _bar(98.0, 106.0, 100.0, 105.5, 200.0),
        _bar(106.0, 110.0, 104.0, 108.0, 150.0),
    ]


def _to_candles(bars: list[tuple], symbol: str) -> list[Candle]:
    candles = []
    for i, (open_, high, low, close, volume) in enumerate(bars):
        open_time = _START + timedelta(days=i)
        candles.append(
            Candle(
                symbol=symbol,
                interval="1d",
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                open_time=open_time,
                close_time=open_time + timedelta(days=1),
            )
        )
    return candles


def _flat_benchmark(length: int) -> list[Candle]:
    return _to_candles(
        [_bar(80_000_000.0, 80_100_000.0, 79_900_000.0, 80_000_000.0, 5.0) for _ in range(length)], "KRW-BTC"
    )


@pytest.mark.P24
def test_no_trades_when_the_market_never_breaks_out() -> None:
    bars = _opening_range_bars(count=25)  # flat throughout - never crosses its own opening high
    candles = _to_candles(bars, "KRW-AAA")

    result = backtest_radar_strategy("KRW-AAA", candles, _flat_benchmark(len(candles)), account_buying_power=10_000_000.0)

    assert result.num_trades == 0
    assert result.win_rate == 0.0
    assert result.total_return_pct == 0.0


@pytest.mark.P24
def test_trade_exits_at_target_when_price_reaches_t2() -> None:
    bars = [
        *_opening_range_bars(),
        *_breakout_confirm_bars(),  # bars 15-16: state commits BREAKOUT on bar 16
        _bar(109.0, 112.0, 106.0, 110.0, 100.0),  # bar 17: entry fills at this bar's open
        _bar(108.0, 150.0, 100.0, 148.0, 60.0),  # bar 18: high clears T2 (108 + (108-95)*3 = 147)
    ]
    candles = _to_candles(bars, "KRW-AAA")

    result = backtest_radar_strategy("KRW-AAA", candles, _flat_benchmark(len(candles)), account_buying_power=10_000_000.0)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.exit_reason == "TARGET"
    assert trade.entry_price == pytest.approx(109.0)  # bar 17's open
    assert trade.exit_price == pytest.approx(147.0)
    assert trade.return_pct > 0
    assert result.win_rate == 1.0


@pytest.mark.P24
def test_trade_exits_at_stop_when_price_falls_through_it() -> None:
    bars = [
        *_opening_range_bars(),
        *_breakout_confirm_bars(),  # bars 15-16
        _bar(109.0, 112.0, 106.0, 110.0, 100.0),  # bar 17: entry fills at this bar's open
        _bar(108.0, 115.0, 90.0, 93.0, 60.0),  # bar 18: low breaches the stop (opening low = 95)
    ]
    candles = _to_candles(bars, "KRW-AAA")

    result = backtest_radar_strategy("KRW-AAA", candles, _flat_benchmark(len(candles)), account_buying_power=10_000_000.0)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.exit_reason == "STOP"
    assert trade.exit_price == pytest.approx(95.0)
    assert trade.return_pct < 0
    assert result.win_rate == 0.0


@pytest.mark.P24
def test_trade_exits_on_pump_risk_state_before_stop_or_target_are_touched() -> None:
    bars = [
        *_opening_range_bars(),
        *_breakout_confirm_bars(),  # bars 15-16
        _bar(110.0, 155.0, 105.0, 150.0, 200.0),  # bar 17: entry fill bar, also an extreme spike
        _bar(100.0, 105.0, 98.0, 102.0, 30.0),  # bar 18: neither stop (95) nor T2 (~147) touched
    ]
    candles = _to_candles(bars, "KRW-AAA")

    result = backtest_radar_strategy("KRW-AAA", candles, _flat_benchmark(len(candles)), account_buying_power=10_000_000.0)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.exit_reason == "STATE_EXIT"
    assert trade.exit_price == pytest.approx(100.0)  # bar 18's open


@pytest.mark.P24
def test_still_open_trade_closes_at_the_last_close_as_end_of_data() -> None:
    bars = [
        *_opening_range_bars(),
        *_breakout_confirm_bars(),  # bars 15-16
        _bar(109.0, 112.0, 106.0, 110.0, 20.0),  # bar 17: entry fills at this bar's open
        _bar(110.0, 114.0, 108.0, 112.0, 20.0),  # bar 18: neither stop nor target touched - data ends here
    ]
    candles = _to_candles(bars, "KRW-AAA")

    result = backtest_radar_strategy("KRW-AAA", candles, _flat_benchmark(len(candles)), account_buying_power=10_000_000.0)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.exit_reason == "END_OF_DATA"
    assert trade.exit_price == pytest.approx(112.0)  # the last candle's close


@pytest.mark.P24
def test_mismatched_series_lengths_are_rejected() -> None:
    candles = _to_candles(_opening_range_bars(count=20), "KRW-AAA")
    benchmark = _flat_benchmark(19)

    with pytest.raises(ValueError, match="same length"):
        backtest_radar_strategy("KRW-AAA", candles, benchmark, account_buying_power=10_000_000.0)
