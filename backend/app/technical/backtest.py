"""Minimal backtest harness for the technical ensemble (P10).

Deliberately simple: walk forward over historical candles with no
lookahead, translate a strategy's per-bar signal into position changes, and
tally trade-level PnL. This is NOT a production backtesting engine - no
fees, spread, slippage, or partial fills (P20 builds that properly for
paper trading). It exists to prove the indicators/strategies above behave
sensibly on a known price path, per P10's "Backtests" acceptance item.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.domain import Candle
from app.technical.strategies import StrategySignal


@dataclass
class Trade:
    entry_price: float
    exit_price: float
    direction: StrategySignal
    return_pct: float


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.return_pct > 0)
        return wins / len(self.trades)

    @property
    def total_return_pct(self) -> float:
        total = 1.0
        for t in self.trades:
            total *= 1 + t.return_pct
        return total - 1.0


def run_backtest(candles: list[Candle], signals: list[StrategySignal]) -> BacktestResult:
    """`signals[i]` is the stance implied by `candles[i]`'s close - to avoid
    lookahead, a stance change is executed at `candles[i + 1]`'s open (the
    next bar after the signal was actually observable), held until the
    signal changes again, and closed the same way.
    """
    if len(candles) != len(signals):
        raise ValueError("candles and signals must be the same length")

    result = BacktestResult()
    position: StrategySignal | None = None
    entry_price: float | None = None

    for i in range(len(candles) - 1):
        desired = signals[i]
        next_open = candles[i + 1].open

        if position is None:
            if desired != StrategySignal.FLAT:
                position = desired
                entry_price = next_open
            continue

        if desired != position:
            assert entry_price is not None
            direction_mult = 1 if position == StrategySignal.LONG else -1
            return_pct = direction_mult * (next_open - entry_price) / entry_price
            result.trades.append(Trade(entry_price, next_open, position, return_pct))

            if desired == StrategySignal.FLAT:
                position = None
                entry_price = None
            else:
                position = desired
                entry_price = next_open

    return result
