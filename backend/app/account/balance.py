"""P45: real combined account-balance aggregation (KIS + Upbit).

Backs the home screen's "총자산"/"자산 추이" cards - a Windows-machine
deployment can have both a KIS domestic-stock account and an Upbit KRW
account funded at once, so "total assets" means the real sum of both,
not either one alone. `fetch_kis_total_value()`/`fetch_upbit_total_value()`
each independently degrade to `None` on any failure (not configured,
network error, malformed response) rather than raising - the same
"partial real data beats no data, never a fabricated 0" rule
`app/api/dashboard.py`'s `/positions/live-prices` (P42) already follows,
now applied to the aggregate figure.

Upbit has no single "total value" field the way KIS's `output2` summary
row does - `GET /v1/accounts` returns one row per currency held
(including `KRW` cash itself), so the KRW value of every non-KRW holding
is computed here by multiplying its real balance by a real, current
`KRW-<currency>` ticker price (`UpbitRestClient.get_ticker_price()`,
already used by `/positions/live-prices`). A currency whose ticker fetch
fails (delisted, temporarily unavailable) is skipped rather than aborting
the whole total - one bad price must not zero out every other real
holding's value.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.rest_client import KisRestClient
from app.integrations.upbit.auth import UpbitAuth
from app.integrations.upbit.errors import UpbitApiError
from app.integrations.upbit.orders import UpbitOrderClient
from app.integrations.upbit.rest_client import UpbitRestClient


@dataclass
class CombinedBalance:
    kis_total_value: float | None
    upbit_total_value: float | None

    @property
    def total_assets(self) -> float:
        """Sums whichever of the two were actually available - `None`
        (not configured, or the real fetch failed) contributes 0, never
        blocks the other broker's real value from showing."""
        return (self.kis_total_value or 0.0) + (self.upbit_total_value or 0.0)


async def fetch_kis_total_value(settings: Settings) -> float | None:
    if not settings.kis_configured:
        return None
    try:
        async with httpx.AsyncClient(base_url=settings.kis_rest_base_url, timeout=10.0) as client:
            auth = KisAuth(client=client, settings=settings)
            rest = KisRestClient(client, auth)
            balance = await rest.get_account_balance(
                settings.kis_cano, settings.kis_acnt_prdt_cd, paper_trading=settings.kis_paper_trading
            )
            return balance.total_value
    except (KisApiError, httpx.HTTPError, KeyError, ValueError):
        return None


async def fetch_upbit_total_value(settings: Settings) -> float | None:
    if not settings.upbit_configured:
        return None
    try:
        async with httpx.AsyncClient(base_url=settings.upbit_rest_base_url, timeout=10.0) as client:
            auth = UpbitAuth(settings.upbit_access_key, settings.upbit_secret_key)
            order_client = UpbitOrderClient(client, auth)
            rest = UpbitRestClient(client)
            accounts = await order_client.get_accounts()

            total = 0.0
            for account in accounts:
                currency = account.get("currency")
                if not currency:
                    continue
                held = float(account.get("balance") or 0) + float(account.get("locked") or 0)
                if held <= 0:
                    continue
                if currency == "KRW":
                    total += held
                    continue
                try:
                    price = await rest.get_ticker_price(f"KRW-{currency}")
                except (UpbitApiError, httpx.HTTPError, KeyError, ValueError):
                    continue
                total += held * price
            return total
    except (UpbitApiError, httpx.HTTPError, KeyError, ValueError):
        return None


async def fetch_combined_balance(settings: Settings) -> CombinedBalance:
    kis_value = await fetch_kis_total_value(settings)
    upbit_value = await fetch_upbit_total_value(settings)
    return CombinedBalance(kis_total_value=kis_value, upbit_total_value=upbit_value)
