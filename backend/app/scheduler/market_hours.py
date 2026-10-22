"""KRX trading-hours gate for the scheduler (P32, pure, no I/O).

Regular KRX session is 09:00-15:30 KST, Monday-Friday - this is that
window and nothing more. It deliberately does **not** know about KRX
public holidays (there's no holiday-calendar source wired into this
project yet, and this project's own discipline is to not fabricate data
it hasn't actually verified) - a holiday will still read as "trading
hours" here, so `scripts/scan_stocks.py`/`scripts/reconfirm_entries.py`
will run a few extra, harmless no-op-ish cycles against a closed market
that day rather than silently skip real trading hours it got wrong.
That's the safe direction to be wrong in: a wasted cycle costs nothing,
a wrongly-skipped real session would.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(15, 30)


def is_krx_trading_hours(now: datetime) -> bool:
    """`now` may be any timezone (including naive, treated as UTC - this
    project's `datetime.now(UTC)` convention elsewhere) - always converted
    to KST before comparing against the session window.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo("UTC"))
    kst_now = now.astimezone(KST)

    if kst_now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    return MARKET_OPEN <= kst_now.time() <= MARKET_CLOSE
