"""Walk-forward historical replay of the stock PRE-BREAKOUT strategy (P40).

Answers "would this strategy's recommendations have made money" by
replaying real historical daily candles bar-by-bar through the exact same
production pipeline `scripts/scan_stocks.py`/`scripts/reconfirm_entries.py`
use live: `score_prebreakout()` (P23), `confirm_entry()` (P27),
`compute_heat_score()` (P35 - a hard TOO_LATE gate, matching
`app.stock_radar.scan.build_confirmed_recommendations()`'s own gate
exactly), `decide_entry_state()` (P36), and `build_stock_recommendation()`
for the actual entry/stop/target. No new signal-generation logic here -
mirrors `app.scan.crypto_backtest`'s "replay the real production
functions, never a parallel simplified copy" design.

**No lookahead**: at day `i`, only `candles[0..i]` are visible when
computing that day's score. The stock pipeline's own two-step design
(score today, gap-check/reconfirm the NEXT trading day before actually
entering) maps naturally onto a backtest: `candles[i+1].open` stands in
for `confirm_entry()`'s live intraday quote - production checks a real
quote during the next session; a backtest only has that day's OHLC, so
the open is the earliest, most conservative substitute (never the day's
low, which would flatter the gap check).

**Not modeled** (same "documented, not hidden" discipline as
`app.scan.crypto_backtest`'s own T1/trailing-stop omission): stocks have
no stateful radar-state machine the way crypto's `CryptoRadarStateTracker`
provides - confirmed by grep, `app/radar/state.py` is never imported
anywhere under `app/stock_radar/`. So there is no "STATE_EXIT" equivalent
here: an open position only ever closes on STOP, TARGET, or END_OF_DATA.
This answers "is the entry signal (score + reconfirm + heat + decision
gate) good", not "how well would P16/P17's trailing-stop position
management have performed" - the same scope boundary the crypto harness
already draws for itself.

**Institutional flow** (P25) is optional and, when provided, is filtered
by calendar date per window rather than sliced positionally, since KIS's
real endpoint returns however much history it feels like
(`KisRestClient.get_investor_trend()`'s own docstring), not a fixed count
aligned to `candles`.

**What this does NOT yet prove**: `too_late_excluded_count`/
`rejected_reconfirm_count`/`no_buy_or_watch_count` below are real counts
of how often each gate actually fired during the replay - not yet a
counterfactual "and skipping it was the right call" (that would need
simulating the trade that *would* have happened had the gate not fired,
then comparing outcomes - a genuine Bad-Trade/Chase-Avoidance-*Rate* KPI,
left for a follow-up once this harness itself is validated).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.models.domain import Candle
from app.radar.regime import classify_market_regime
from app.stock_radar.decision import DecisionState, decide_entry_state
from app.stock_radar.entry_confirmation import EntryVerdict, confirm_entry
from app.stock_radar.investor_flow import InvestorFlowBar
from app.stock_radar.overheat import HeatStatus, compute_heat_score
from app.stock_radar.recommendation import build_stock_recommendation
from app.stock_radar.scoring import (
    DEFAULT_ATR_LOOKBACK,
    DEFAULT_ATR_WINDOW,
    SCORE_MAX_AVAILABLE,
    score_prebreakout,
)

_MIN_BARS = DEFAULT_ATR_LOOKBACK + DEFAULT_ATR_WINDOW
_MIN_BENCHMARK_BARS = 21  # classify_market_regime()'s own ma_window(20) + 1
_ENTRY_FILTERS_TOTAL_NO_FLOW = 7
_ENTRY_FILTERS_TOTAL_WITH_FLOW = 8
_ENTERABLE_STATES = (DecisionState.BUY, DecisionState.STRONG_BUY)


@dataclass
class BacktestTrade:
    symbol: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    exit_reason: str  # "STOP" | "TARGET" | "END_OF_DATA"
    return_pct: float


@dataclass
class BacktestResult:
    trades: list[BacktestTrade] = field(default_factory=list)
    too_late_excluded_count: int = 0
    rejected_reconfirm_count: int = 0
    no_buy_or_watch_count: int = 0

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


def _flow_bars_up_to(bars: list[InvestorFlowBar] | None, as_of: datetime) -> list[InvestorFlowBar] | None:
    if bars is None:
        return None
    return [b for b in bars if b.date <= as_of]


def _check_exit(open_trade: _OpenTrade, next_bar: Candle) -> tuple[str, float] | None:
    """Same conservative ordering as `app.scan.crypto_backtest._check_exit()`
    - the stop is checked before the target, so a bar that touches both in
    one day is scored as the loss rather than assuming the more favorable
    order."""
    if next_bar.low <= open_trade.stop_price:
        return "STOP", open_trade.stop_price
    if next_bar.high >= open_trade.t2_price:
        return "TARGET", open_trade.t2_price
    return None


def backtest_prebreakout_strategy(
    symbol: str,
    candles: list[Candle],
    benchmark_candles: list[Candle],
    account_buying_power: float,
    investor_flow_bars: list[InvestorFlowBar] | None = None,
    window_size: int = _MIN_BARS,
) -> BacktestResult:
    """`candles`/`benchmark_candles` must be chronological (oldest first)
    and the same length (bar-aligned) - exactly what two independent
    `get_daily_prices()`/`get_index_daily_prices()` calls over the same
    date range naturally produce, same requirement
    `app.scan.crypto_backtest.backtest_radar_strategy()` already has.
    """
    if len(candles) != len(benchmark_candles):
        raise ValueError("candles and benchmark_candles must be the same length (bar-aligned)")

    result = BacktestResult()
    open_trade: _OpenTrade | None = None

    if len(candles) < window_size + 1 or len(benchmark_candles) < _MIN_BENCHMARK_BARS:
        return result

    for i in range(window_size - 1, len(candles) - 1):
        next_bar = candles[i + 1]

        if open_trade is not None:
            exit_outcome = _check_exit(open_trade, next_bar)
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

        window = candles[max(0, i - window_size + 1) : i + 1]
        benchmark_window = benchmark_candles[max(0, i - window_size + 1) : i + 1]
        flow_window = _flow_bars_up_to(investor_flow_bars, window[-1].open_time)

        score = score_prebreakout(symbol, window, benchmark_window, investor_flow_bars=flow_window)
        if score is None:
            continue

        regime = classify_market_regime(benchmark_window)
        confirmation = confirm_entry(score, current_price=next_bar.open, regime=regime)
        if confirmation.verdict != EntryVerdict.CONFIRMED:
            result.rejected_reconfirm_count += 1
            continue

        heat_window = candles[max(0, i + 1 - window_size + 1) : i + 2]  # extends through next_bar
        heat = compute_heat_score(heat_window, entry_reference_price=score.reference_close, gap_pct=confirmation.gap_pct)
        if heat is None:
            continue
        if heat.status == HeatStatus.TOO_LATE:
            result.too_late_excluded_count += 1
            continue

        normalized_score = min(max(score.total_score / score.max_available * 100, 0.0), 100.0)
        filters_passed = len(score.positive)
        filters_total = (
            _ENTRY_FILTERS_TOTAL_WITH_FLOW if score.max_available > SCORE_MAX_AVAILABLE else _ENTRY_FILTERS_TOTAL_NO_FLOW
        )
        decision = decide_entry_state(normalized_score, regime, heat.status, filters_passed, filters_total)
        if decision.state not in _ENTERABLE_STATES:
            result.no_buy_or_watch_count += 1
            continue

        rec = build_stock_recommendation(
            score, confirmation, recent_candles=heat_window, account_buying_power=account_buying_power,
            now=next_bar.close_time,
        )
        if rec is not None:
            open_trade = _OpenTrade(
                entry_time=next_bar.close_time, entry_price=rec.entry_low,
                stop_price=rec.stop_price, t2_price=rec.t2_price,
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
