"""Historical replay of the crypto radar recommendation strategy (P24).

Answers "would this strategy's recommendations have made money" by
replaying real historical candles bar-by-bar through the *exact same*
signal pipeline `app/scan/crypto_scan.py` uses live: `CryptoRadarStateTracker`
(P9's full hysteresis - a backtest has the whole history available, so
unlike the live scan's single-shot simplification there is no reason to
skip the smoothing), `opening_range`/RVOL/CLV/relative-strength-vs-BTC/
pump-risk (P4/P8), and P6's `build_recommendation()` - unchanged. No new
signal-generation logic; this module is only a replay loop and a
trade-outcome tally, mirroring the "deliberately simple, no lookahead"
style of `app/technical/backtest.py` and `app/paper_trading/replay_engine.py`.

At each bar `i`, the signal is computed from a trailing window of the same
size (`window_size`, default `crypto_scan.CANDLE_COUNT`) that a live scan
running at that moment would have fetched - so `opening_range()`'s "first N
bars" means the same thing here as it does in `crypto_scan.py`: the start
of that trailing window, not a real intraday session open (crypto has none
- see `crypto_scan.py`'s own module docstring for this same simplification).

Exit rule (documented, not hidden): once a recommendation opens a trade, it
closes on whichever comes first, checked in this conservative order -
`stop_price` (checked before the target, so a bar that touches both in one
day is scored as the loss rather than assuming the more favorable order),
the T2 target, the radar state degrading to FAILED_BREAKOUT/DISTRIBUTION/
AVOID/PUMP_RISK, or the data running out. T1/runner partial-exits and
trailing-stop tightening (P16) are real position-management features this
backtest does not model; it answers "is the entry signal good", not "how
well would P16/P17 have managed the exit".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.models.domain import AssetType, Candle
from app.radar.crypto_features import (
    classify_btc_regime,
    pump_risk_score,
    relative_strength_vs_btc,
    relative_volume,
)
from app.radar.crypto_state import CryptoRadarStateTracker
from app.radar.features import close_location_value, opening_range
from app.radar.state import RadarState
from app.recommendation.engine import RecommendationInputs, build_recommendation
from app.scan.crypto_scan import CANDLE_COUNT, OPENING_RANGE_BARS

_PUMP_RISK_LOOKBACK = 10  # must match pump_risk_score()'s own default
_DEGRADED_STATES = (
    RadarState.FAILED_BREAKOUT,
    RadarState.DISTRIBUTION,
    RadarState.AVOID,
    RadarState.PUMP_RISK,
)


@dataclass
class BacktestTrade:
    symbol: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    exit_reason: str  # "STOP" | "TARGET" | "STATE_EXIT" | "END_OF_DATA"
    return_pct: float


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)

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


@dataclass
class _OpenTrade:
    entry_time: datetime
    entry_price: float
    stop_price: float
    t2_price: float


def _check_exit(open_trade: _OpenTrade, state: RadarState, next_bar: Candle) -> tuple[str, float] | None:
    if next_bar.low <= open_trade.stop_price:
        return "STOP", open_trade.stop_price
    if next_bar.high >= open_trade.t2_price:
        return "TARGET", open_trade.t2_price
    if state in _DEGRADED_STATES:
        return "STATE_EXIT", next_bar.open
    return None


def backtest_radar_strategy(
    symbol: str,
    candles: list[Candle],
    benchmark_candles: list[Candle],
    account_buying_power: float,
    opening_range_bars: int = OPENING_RANGE_BARS,
    window_size: int = CANDLE_COUNT,
) -> BacktestResult:
    """`candles`/`benchmark_candles` must be chronological (oldest first)
    and day-aligned (same length, index `i` in both is the same calendar
    bar) - exactly what two independent `get_daily_candles()` calls made
    around the same time naturally produce.
    """
    if len(candles) != len(benchmark_candles):
        raise ValueError("candles and benchmark_candles must be the same length (bar-aligned)")

    min_bars = max(opening_range_bars + 1, _PUMP_RISK_LOOKBACK + 1, 2)
    result = BacktestResult()
    tracker = CryptoRadarStateTracker()
    open_trade: _OpenTrade | None = None

    for i in range(min_bars - 1, len(candles) - 1):
        window = candles[max(0, i - window_size + 1) : i + 1]
        benchmark_window = benchmark_candles[max(0, i - window_size + 1) : i + 1]
        latest = window[-1]
        opening = opening_range(window, opening_range_bars)
        history = window[:-1]
        avg_volume = sum(c.volume for c in history) / len(history) if history else 0.0
        rvol = relative_volume(latest.volume, avg_volume)
        clv = close_location_value(latest)
        pump_risk = pump_risk_score(window)
        relative_strength_value = relative_strength_vs_btc(window, benchmark_window)
        regime = classify_btc_regime(benchmark_window)

        state = tracker.update(latest.close, opening.high, rvol, clv, pump_risk)
        next_bar = candles[i + 1]

        if open_trade is not None:
            exit_outcome = _check_exit(open_trade, state, next_bar)
            if exit_outcome is not None:
                reason, exit_price = exit_outcome
                return_pct = (exit_price - open_trade.entry_price) / open_trade.entry_price
                result.trades.append(
                    BacktestTrade(
                        symbol=symbol,
                        entry_time=open_trade.entry_time,
                        entry_price=open_trade.entry_price,
                        exit_time=next_bar.close_time,
                        exit_price=exit_price,
                        exit_reason=reason,
                        return_pct=return_pct,
                    )
                )
                open_trade = None
            continue

        inputs = RecommendationInputs(
            symbol=symbol,
            asset_type=AssetType.CRYPTO,
            price=latest.close,
            breakout_level=opening.high,
            structural_stop=opening.low,
            rvol=rvol,
            clv=clv,
            relative_strength_value=relative_strength_value,
            regime=regime,
            radar_state=state,
            account_buying_power=account_buying_power,
        )
        rec = build_recommendation(inputs)
        if rec is not None:
            open_trade = _OpenTrade(
                entry_time=next_bar.open_time,
                entry_price=next_bar.open,
                stop_price=rec.stop_price,
                t2_price=rec.t2_price,
            )

    if open_trade is not None:
        last = candles[-1]
        return_pct = (last.close - open_trade.entry_price) / open_trade.entry_price
        result.trades.append(
            BacktestTrade(
                symbol=symbol,
                entry_time=open_trade.entry_time,
                entry_price=open_trade.entry_price,
                exit_time=last.close_time,
                exit_price=last.close,
                exit_reason="END_OF_DATA",
                return_pct=return_pct,
            )
        )

    return result
