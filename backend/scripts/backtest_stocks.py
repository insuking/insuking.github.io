#!/usr/bin/env python3
"""Backtest the stock PRE-BREAKOUT strategy against real KIS daily candles (P40).

Makes real HTTP requests to KIS (requires `KIS_APP_KEY`/`KIS_APP_SECRET` -
see docs/KIS_SETUP.md) and replays `app/stock_radar/backtest.py`'s
walk-forward strategy over each symbol's actual price history. This is
the stock-radar equivalent of `scripts/backtest_crypto.py` (P24) - same
"replay the real production pipeline, print a report, touch nothing in
the DB or a real/paper account" shape.

**Universe**: `BACKTEST_SYMBOLS` (comma-separated KRX codes) if set,
otherwise the same small 5-symbol default list `scripts/scan_stocks.py`
falls back to (`STOCK_SCAN_UNIVERSE=DEFAULT`'s list) - deliberately not
the full rotating universe (P39): each symbol here costs a daily-price
call plus an optional investor-flow call, and a meaningful backtest needs
`BACKTEST_HISTORY_DAYS` of history per symbol, so backtesting hundreds of
symbols in one run would take far longer than a live scan of the same
size. Widening this once the harness itself is proven is a natural
follow-up, not something to rush into this first pass.

**Institutional flow** (P25) is fetched best-effort per symbol via
`KisRestClient.get_investor_trend()` - a failure degrades that one
symbol's backtest to the 65-point price/volume-only ceiling (`None`
passed to `backtest_prebreakout_strategy()`), never aborts the run.

Nothing here writes to the database or touches a real/paper account -
this only prints a report.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, ".")

import httpx

from app.core.config import get_settings
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.rest_client import KOSPI_INDEX_CODE, KisRestClient
from app.stock_radar.backtest import BacktestResult, backtest_prebreakout_strategy
from app.stock_radar.investor_flow import InvestorFlowBar

_DEFAULT_BUYING_POWER = 10_000_000.0  # KRW placeholder - see scripts/scan_stocks.py's own note
_DEFAULT_HISTORY_DAYS = 500  # calendar days - the ~74-bar scoring warmup needs real trading days left over
_DEFAULT_SYMBOLS = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "051910",  # LG화학
    "005380",  # 현대차
    "035420",  # NAVER
]


async def _fetch_investor_flow(rest: KisRestClient, symbol: str) -> list[InvestorFlowBar] | None:
    try:
        bars = await rest.get_investor_trend(symbol)
    except (KisApiError, httpx.HTTPError, KeyError, ValueError) as exc:
        print(f"  ({symbol}: investor-flow fetch failed ({exc!r}) - scoring without it)")
        return None
    return bars or None


async def run() -> None:
    settings = get_settings()
    if not settings.kis_configured:
        print("KIS_APP_KEY/KIS_APP_SECRET are not set - see docs/KIS_SETUP.md. Nothing to backtest yet.")
        return

    buying_power_raw = os.environ.get("SCAN_ACCOUNT_BUYING_POWER")
    account_buying_power = float(buying_power_raw) if buying_power_raw else _DEFAULT_BUYING_POWER

    symbols_raw = os.environ.get("BACKTEST_SYMBOLS")
    symbols = [s.strip() for s in symbols_raw.split(",")] if symbols_raw else _DEFAULT_SYMBOLS

    history_days = int(os.environ.get("BACKTEST_HISTORY_DAYS", _DEFAULT_HISTORY_DAYS))
    end_date = datetime.now(UTC).strftime("%Y%m%d")
    start_date = (datetime.now(UTC) - timedelta(days=history_days)).strftime("%Y%m%d")

    async with httpx.AsyncClient(base_url=settings.kis_rest_base_url) as client:
        auth = KisAuth(client=client, settings=settings)
        rest = KisRestClient(client, auth)

        try:
            benchmark_candles = await rest.get_index_daily_prices(KOSPI_INDEX_CODE, start_date, end_date)
        except (KisApiError, KeyError, ValueError) as exc:
            print(f"Real KOSPI index fetch failed ({exc!r}) - can't backtest without a real benchmark. Aborting.")
            return
        if not benchmark_candles:
            print("Real KOSPI index fetch returned no candles - can't backtest without a real benchmark. Aborting.")
            return

        print(f"Backtesting {len(symbols)} symbol(s) over {len(benchmark_candles)} daily bars each...\n")

        results: dict[str, BacktestResult] = {}
        for symbol in symbols:
            candles = await rest.get_daily_prices(symbol, start_date, end_date)
            if len(candles) != len(benchmark_candles):
                print(f"{symbol}: skipped (only {len(candles)} bars of history, need {len(benchmark_candles)})")
                continue
            flow_bars = await _fetch_investor_flow(rest, symbol)
            results[symbol] = backtest_prebreakout_strategy(
                symbol, candles, benchmark_candles, account_buying_power=account_buying_power,
                investor_flow_bars=flow_bars,
            )

    total_trades = 0
    total_too_late = 0
    total_rejected_reconfirm = 0
    total_no_buy = 0
    for symbol, result in sorted(results.items(), key=lambda kv: kv[1].num_trades, reverse=True):
        total_too_late += result.too_late_excluded_count
        total_rejected_reconfirm += result.rejected_reconfirm_count
        total_no_buy += result.no_buy_or_watch_count
        if result.num_trades == 0:
            print(f"{symbol}: no eligible entries in this window")
            continue
        total_trades += result.num_trades
        print(
            f"{symbol}: {result.num_trades} trades, "
            f"win rate {result.win_rate * 100:.0f}%, "
            f"compounded return {result.total_return_pct * 100:+.1f}%"
        )

    print(
        f"\nGate activity across all symbols: {total_too_late} TOO_LATE exclusions, "
        f"{total_rejected_reconfirm} reconfirm rejections, {total_no_buy} WATCH/NO_BUY days "
        "(counts of how often each gate fired, not yet a validated avoidance rate - see "
        "app/stock_radar/backtest.py's module docstring)."
    )

    if total_trades == 0:
        print("No trades were generated by any symbol in this window - nothing else to summarize.")
        return

    print(
        f"\n{total_trades} total trades across {len(results)} symbol(s). "
        "Per-trade fees/slippage are NOT modeled here (see app/stock_radar/backtest.py's "
        "module docstring) - treat this as a signal-quality check, not a net-PnL forecast."
    )


if __name__ == "__main__":
    asyncio.run(run())
