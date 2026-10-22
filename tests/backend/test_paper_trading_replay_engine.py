"""P20 acceptance: replay_engine.py's no-lookahead execution and realistic
net-of-cost PnL - mirrors technical/test_backtest.py's fixtures but checks
that costs actually reduce the return relative to the gross move, and that
a signal at bar i never executes before bar i + 1.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import Candle
from app.paper_trading.cost_model import TradingCosts
from app.paper_trading.replay_engine import run_replay
from app.technical.strategies import StrategySignal

pytestmark = pytest.mark.P20

_COSTS = TradingCosts(commission_rate=0.001, sell_tax_rate=0.002)
_START = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def _candle(i: int, open_: float, close: float) -> Candle:
    ts = _START + timedelta(minutes=i)
    return Candle(
        symbol="TEST",
        interval="1m",
        open=open_,
        high=max(open_, close) + 0.5,
        low=min(open_, close) - 0.5,
        close=close,
        volume=1000.0,
        open_time=ts,
        close_time=ts + timedelta(minutes=1),
    )


def test_mismatched_lengths_raise() -> None:
    with pytest.raises(ValueError, match="same length"):
        run_replay([_candle(0, 100.0, 100.0)], [], _COSTS)


def test_no_trades_when_always_flat() -> None:
    candles = [_candle(i, 100.0, 100.0) for i in range(5)]
    signals = [StrategySignal.FLAT] * 5
    result = run_replay(candles, signals, _COSTS)
    assert result.num_trades == 0
    assert result.total_net_return_pct == 0.0


def test_long_trade_enters_at_next_bar_not_the_signal_bar() -> None:
    # signals[0]=LONG (bar 0's stance) executes at bar 1's open (100), not
    # bar 0's own open (50) - if execution used bar 0's price instead,
    # entry_price would come out near 50.
    candles = [_candle(0, 50.0, 50.0), _candle(1, 100.0, 100.0), _candle(2, 100.0, 100.0)]
    signals = [StrategySignal.LONG, StrategySignal.FLAT, StrategySignal.FLAT]
    result = run_replay(candles, signals, _COSTS)

    assert result.num_trades == 1
    assert result.trades[0].entry_price > 90.0  # bar 1's open (~100), not bar 0's (50)


def test_net_return_is_lower_than_gross_return_due_to_costs() -> None:
    candles = [_candle(0, 100.0, 100.0), _candle(1, 100.0, 100.0), _candle(2, 200.0, 200.0)]
    signals = [StrategySignal.LONG, StrategySignal.FLAT, StrategySignal.FLAT]
    result = run_replay(candles, signals, _COSTS)

    assert result.num_trades == 1
    trade = result.trades[0]
    assert trade.total_cost > 0
    assert trade.net_return_pct < trade.gross_return_pct


def test_win_rate_and_total_return_reflect_net_pnl() -> None:
    # Bar-by-bar opens: [100, 100, 100, 110, 100, 50]. Trade 1 enters at
    # bar 1's open (100) and exits at bar 3's open (110): a ~10% gain.
    # Trade 2 enters at bar 4's open (100) and exits at bar 5's open (50):
    # a ~50% loss - large enough that it dominates the total.
    opens = [100.0, 100.0, 100.0, 110.0, 100.0, 50.0]
    candles = [_candle(i, o, o) for i, o in enumerate(opens)]
    signals = [
        StrategySignal.LONG,
        StrategySignal.LONG,
        StrategySignal.FLAT,
        StrategySignal.LONG,
        StrategySignal.FLAT,
        StrategySignal.FLAT,
    ]
    result = run_replay(candles, signals, _COSTS)

    assert result.num_trades == 2
    assert result.win_rate == pytest.approx(0.5)
    assert result.total_net_return_pct < 0  # the loss trade dominates
