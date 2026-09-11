#!/usr/bin/env python3
"""P45: periodically persist a real combined-balance snapshot (KIS +
Upbit) so the home screen's "자산 추이" (asset trend) chart has real
history to plot, not just a live "right now" figure.

Meant to run on the scheduler's crypto-scan cadence
(`scripts/scheduler.py`'s `_CRYPTO_INTERVAL_SECONDS`, 24/7 - unlike the
stock scan this needs no KRX-trading-hours gate, since account balances
move any time an Upbit position's price moves). Safe to run before
either broker is configured - `app.account.balance.fetch_combined_balance()`
degrades each side to `None` independently rather than raising, and
`total_assets` is still a real (zero) number in that case, not fabricated.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

sys.path.insert(0, ".")

from app.account.balance import fetch_combined_balance
from app.account.persistence import persist_balance_snapshot
from app.core.config import get_settings
from app.db.session import session_scope


async def run() -> None:
    settings = get_settings()
    observed_at = datetime.now(UTC)

    balance = await fetch_combined_balance(settings)

    async with session_scope() as session:
        await persist_balance_snapshot(session, balance, observed_at)
        await session.commit()


if __name__ == "__main__":
    asyncio.run(run())
