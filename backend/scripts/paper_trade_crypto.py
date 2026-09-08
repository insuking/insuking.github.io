#!/usr/bin/env python3
"""Run one round of auto crypto paper trading (P24): check existing paper
positions for a stop/target hit, then open new ones from a fresh real
crypto scan (P23).

Real HTTP requests to Upbit (no API key needed), real database writes to
this deployment's `paper_accounts`/`paper_orders`/`paper_fills`/
`paper_positions` tables - never the real `positions`/`orders`/`fills`
tables, never a real broker, `LIVE_TRADING` stays irrelevant here. See
app/scan/auto_paper_trade.py's module docstring for exactly what this does
and does not model (no P18 risk budget, no T1/runner/trailing-stop).

Meant to be re-run repeatedly (a cron job, or by hand) - each run is a
complete decide-and-act cycle: close what should close, open what's newly
recommended, print what happened. `PAPER_TRADE_ACCOUNT_ID` picks which
paper account to run against (default below); `SCAN_ACCOUNT_BUYING_POWER`
only matters on an account's first-ever run (see get_or_create_account -
after that the account's real simulated cash balance is used).
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, ".")

import httpx

from app.core.config import get_settings
from app.db.session import session_scope
from app.integrations.upbit.rest_client import UpbitRestClient
from app.paper_trading.ledger import get_or_create_account
from app.scan.auto_paper_trade import DEFAULT_STARTING_CASH, run_auto_paper_trading

_DEFAULT_ACCOUNT_ID = "PAPER_UPBIT_AUTO"


async def run() -> None:
    settings = get_settings()
    account_id = os.environ.get("PAPER_TRADE_ACCOUNT_ID", _DEFAULT_ACCOUNT_ID)
    starting_cash_raw = os.environ.get("SCAN_ACCOUNT_BUYING_POWER")
    starting_cash = float(starting_cash_raw) if starting_cash_raw else DEFAULT_STARTING_CASH

    async with httpx.AsyncClient(base_url=settings.upbit_rest_base_url) as client:
        rest = UpbitRestClient(client)
        async with session_scope() as session:
            report = await run_auto_paper_trading(session, rest, account_id, starting_cash=starting_cash)
            account = await get_or_create_account(session, account_id, "CRYPTO", starting_cash)

    if report.closed:
        print("Closed:")
        for c in report.closed:
            print(f"  {c.symbol}  {c.exit_reason}  qty={c.quantity:.6f}  @ {c.exit_price:,.2f}")
    if report.opened:
        print("Opened:")
        for o in report.opened:
            print(
                f"  {o.symbol}  qty={o.quantity:.6f}  @ {o.entry_price:,.2f}  "
                f"stop={o.stop_price:,.2f}  target={o.t2_price:,.2f}"
            )
    if report.skipped:
        print("Skipped:")
        for s in report.skipped:
            print(f"  {s.symbol}: {s.reason}")
    if report.rejected_orders:
        print("Rejected:")
        for r in report.rejected_orders:
            print(f"  {r}")

    if not (report.closed or report.opened or report.skipped or report.rejected_orders):
        print("No eligible recommendations and no positions to check this run.")

    print(f"\nAccount {account_id}: cash={account.cash_balance:,.2f} KRW")


if __name__ == "__main__":
    asyncio.run(run())
