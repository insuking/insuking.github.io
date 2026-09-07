"""Historical replay (P20) - the "properly done" backtest
`app/technical/backtest.py` deferred: same no-lookahead rule (a signal
observed at bar `i`'s close executes at bar `i + 1`'s open, never at its
own close), but every execution now goes through `fill_simulator` and
`cost_model` instead of assuming a costless fill at the exact next open.

The synthetic `MarketSnapshot` for bar `i + 1` treats its `open` as the
mid price, derives a bid/ask from a caller-supplied spread, and uses its
`volume` as the available liquidity - real spread/volume data (P3/P7's
tick and orderbook feeds) is a strictly better input than this when
available; this is the fallback for plain OHLCV history.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.domain import Candle
from app.paper_trading.cost_model import TradingCosts, total_transaction_cost
from app.paper_trading.fill_simulator import MarketSnapshot, simulate_fill
from app.technical.strategies import StrategySignal

DEFAULT_SPREAD_BPS = 5.0


@dataclass
class ReplayTrade:
    entry_price: float
    exit_price: float
    direction: StrategySignal
    quantity: float
    gross_return_pct: float
    total_cost: float
    net_return_pct: float


@dataclass
class ReplayResult:
    trades: list[ReplayTrade] = field(default_factory=list)

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.net_return_pct > 0)
        return wins / len(self.trades)

    @property
    def total_net_return_pct(self) -> float:
        total = 1.0
        for t in self.trades:
            total *= 1 + t.net_return_pct
        return total - 1.0


def _snapshot_for_bar(candle: Candle, spread_bps: float) -> MarketSnapshot:
    half_spread = candle.open * (spread_bps / 10_000) / 2
    return MarketSnapshot(
        bid=candle.open - half_spread, ask=candle.open + half_spread, available_volume=candle.volume
    )


def run_replay(
    candles: list[Candle],
    signals: list[StrategySignal],
    costs: TradingCosts,
    *,
    quantity: float = 1.0,
    spread_bps: float = DEFAULT_SPREAD_BPS,
) -> ReplayResult:
    """`signals[i]` is the stance implied by `candles[i]`'s close - executed
    at `candles[i + 1]` via a simulated fill, exactly like
    `technical.backtest.run_backtest`'s no-lookahead rule, but now pricing
    each entry/exit through `fill_simulator` + `cost_model` instead of an
    idealized costless fill at the next open.
    """
    if len(candles) != len(signals):
        raise ValueError("candles and signals must be the same length")

    result = ReplayResult()
    position: StrategySignal | None = None
    entry_price: float | None = None

    for i in range(len(candles) - 1):
        desired = signals[i]
        next_candle = candles[i + 1]
        snapshot = _snapshot_for_bar(next_candle, spread_bps)

        if position is None:
            if desired != StrategySignal.FLAT:
                side = "BUY" if desired == StrategySignal.LONG else "SELL"
                fill = simulate_fill(
                    side=side, quantity=quantity, order_type="MARKET", limit_price=None, snapshot=snapshot
                )
                if fill.fill_quantity > 0:
                    position = desired
                    entry_price = fill.fill_price
            continue

        if desired != position:
            assert entry_price is not None
            exit_side = "SELL" if position == StrategySignal.LONG else "BUY"
            fill = simulate_fill(
                side=exit_side,
                quantity=quantity,
                order_type="MARKET",
                limit_price=None,
                snapshot=snapshot,
            )
            if fill.fill_quantity <= 0:
                continue

            exit_price = fill.fill_price
            direction_mult = 1 if position == StrategySignal.LONG else -1
            gross_return_pct = direction_mult * (exit_price - entry_price) / entry_price

            entry_notional = quantity * entry_price
            exit_notional = quantity * exit_price
            entry_side = "BUY" if position == StrategySignal.LONG else "SELL"
            total_cost = total_transaction_cost(entry_notional, entry_side, costs) + (
                total_transaction_cost(exit_notional, exit_side, costs)
            )
            net_return_pct = gross_return_pct - total_cost / entry_notional

            result.trades.append(
                ReplayTrade(
                    entry_price=entry_price,
                    exit_price=exit_price,
                    direction=position,
                    quantity=quantity,
                    gross_return_pct=gross_return_pct,
                    total_cost=total_cost,
                    net_return_pct=net_return_pct,
                )
            )

            if desired == StrategySignal.FLAT:
                position = None
                entry_price = None
            else:
                side = "BUY" if desired == StrategySignal.LONG else "SELL"
                entry_fill = simulate_fill(
                    side=side, quantity=quantity, order_type="MARKET", limit_price=None, snapshot=snapshot
                )
                if entry_fill.fill_quantity > 0:
                    position = desired
                    entry_price = entry_fill.fill_price
                else:
                    position = None
                    entry_price = None

    return result
