#!/usr/bin/env python3
"""P32: run the crypto/stock scan-and-reconfirm scripts on a loop.

**The gap this closes**: every recommendation-producing script
(`scan_crypto.py`, `scan_stocks.py`, `reconfirm_entries.py`) already
existed and already worked, but nothing ever *ran* them - a real
docker-compose deployment brought up `postgres`/`redis`/`backend`/
`frontend` and then just sat there. The "추천" tab and Home's "TOP 추천"
staying empty in a real deployment wasn't a display bug or a scoring
bug; it was that literally no recommendation had ever been computed,
because running these scripts was left as a manual, easy-to-forget step.
This script is that missing "someone has to remember to run it" piece,
automated.

**Still never autonomous trading**: this only scores candidates and
persists `Recommendation` rows - exactly what running these scripts by
hand already did, and nothing more. It never creates an `Approval` and
never places an order; a human still has to open the app, see the
recommendation, and tap 승인 through the existing Kakao-approval flow.
The project's standing "never fully autonomous" rule is untouched here -
this automates read-only market analysis, not execution.

**Cadence**: the crypto scan runs on every cycle (Upbit's public REST API,
no key needed, and crypto trades 24/7 - see `scan_crypto.py`'s own
docstring). The stock scan + reconfirm pass only runs inside real KRX
trading hours (`app.scheduler.market_hours.is_krx_trading_hours()`) and
no more often than `SCHEDULER_STOCK_INTERVAL_SECONDS` - scanning stocks
outside trading hours would just recompute the same stale daily candles
for no reason, and `reconfirm_entries.py`'s own docstring already warns
that confirming outside trading hours proves nothing. Both scripts
already no-op cleanly with a printed message when `KIS_APP_KEY`/
`KIS_APP_SECRET` aren't set (see their own `run()`), so this loop is
safe to start even before KIS credentials are configured. The P45
balance snapshot also runs every cycle alongside the crypto scan (real
account balances move any time, not just during KRX hours) - see
`scripts/snapshot_balance.py`'s own docstring.

**Failure handling**: each script's `run()` is wrapped in `_run_safely()`
- an exception from one cycle (a transient KIS/Upbit error, a DB hiccup)
is logged and swallowed, never crashes the loop. Matches the
degrade-not-crash pattern already used inside `app/stock_radar/scan.py`.

**P38 macro pass**: `scan_macro.py`'s premarket check is a once-a-day,
wall-clock-time job, not an interval job like the crypto/stock passes -
it runs the first cycle whose KST time-of-day is at or after 08:20 and
that hasn't already run that KST calendar date, tracked by
`last_macro_run_date` (a `date`, not a timestamp) the same way
`last_stock_run_at` tracks the stock pass's interval.
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from collections.abc import Awaitable
from datetime import UTC, date, datetime, time

sys.path.insert(0, ".")

from app.scheduler.market_hours import KST, is_krx_trading_hours
from scripts import reconfirm_entries, scan_crypto, scan_macro, scan_stocks, snapshot_balance

_CRYPTO_INTERVAL_SECONDS = int(os.environ.get("SCHEDULER_CRYPTO_INTERVAL_SECONDS", "300"))
_STOCK_INTERVAL_SECONDS = int(os.environ.get("SCHEDULER_STOCK_INTERVAL_SECONDS", "1800"))
_MACRO_CHECK_TIME = time(8, 20)


async def _run_safely(label: str, coro: Awaitable[None]) -> None:
    try:
        await coro
    except Exception:  # noqa: BLE001 - one bad cycle must never take the scheduler down
        print(f"[scheduler] {label} run failed:")
        traceback.print_exc()


async def run_cycle(
    now: datetime,
    seconds_since_last_stock_run: float | None,
    last_macro_run_date: date | None = None,
) -> tuple[bool, bool]:
    """One iteration: always runs the crypto scan, runs the stock scan +
    reconfirm pass if `now` is inside KRX trading hours AND either the
    stock pass has never run yet (`seconds_since_last_stock_run is None`)
    or at least `SCHEDULER_STOCK_INTERVAL_SECONDS` has passed since it
    last did, and runs the P38 macro pass if `now`'s KST time-of-day is
    at or after 08:20 and it hasn't already run on `now`'s KST calendar
    date. Returns `(ran_stock, ran_macro)` as plain return values rather
    than mutated counters, so the caller decides how to track "last run"
    and this function stays trivially testable with monkeypatched
    scan/reconfirm coroutines.
    """
    await _run_safely("crypto scan", scan_crypto.run())
    await _run_safely("balance snapshot", snapshot_balance.run())

    should_run_stock = is_krx_trading_hours(now) and (
        seconds_since_last_stock_run is None or seconds_since_last_stock_run >= _STOCK_INTERVAL_SECONDS
    )
    if should_run_stock:
        await _run_safely("stock scan", scan_stocks.run())
        await _run_safely("stock reconfirm", reconfirm_entries.run())

    now_kst = now.astimezone(KST) if now.tzinfo is not None else now.replace(tzinfo=UTC).astimezone(KST)
    should_run_macro = now_kst.time() >= _MACRO_CHECK_TIME and last_macro_run_date != now_kst.date()
    if should_run_macro:
        await _run_safely("macro check", scan_macro.run())

    return should_run_stock, should_run_macro


async def run_forever() -> None:
    last_stock_run_at: float | None = None
    last_macro_run_date: date | None = None
    print(
        f"[scheduler] started - crypto scan every {_CRYPTO_INTERVAL_SECONDS}s (24/7), "
        f"stock scan+reconfirm every {_STOCK_INTERVAL_SECONDS}s during KRX trading hours "
        "(09:00-15:30 KST, Mon-Fri), macro check once daily at/after 08:20 KST."
    )
    while True:
        loop_time = asyncio.get_event_loop().time()
        elapsed = None if last_stock_run_at is None else loop_time - last_stock_run_at

        now = datetime.now(UTC)
        ran_stock, ran_macro = await run_cycle(now, elapsed, last_macro_run_date)
        if ran_stock:
            last_stock_run_at = asyncio.get_event_loop().time()
        if ran_macro:
            last_macro_run_date = now.astimezone(KST).date()

        await asyncio.sleep(_CRYPTO_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run_forever())
