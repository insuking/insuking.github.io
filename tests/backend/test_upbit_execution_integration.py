"""P15 acceptance: real connection for Upbit's authenticated order endpoints,
when credentials exist - otherwise BLOCKED.

This deliberately does **not** place, modify, or cancel a real order -
`UpbitExecutionProvider.place_order`/`cancel_order` are never called here,
regardless of `LIVE_TRADING`. This only proves the JWT request-signing in
`app/integrations/upbit/auth.py` actually authenticates against Upbit's
real servers, via the read-only `list_orders` call (the same one
`UpbitExecutionProvider.reconcile_order()` uses) - if the JWT were built
wrong, this call would fail with an auth error before any order-placement
code could ever be trusted.
"""

import httpx
import pytest

from app.core.config import get_settings
from app.integrations.upbit.auth import UpbitAuth
from app.integrations.upbit.orders import UpbitOrderClient

pytestmark = [
    pytest.mark.P15,
    pytest.mark.skipif(
        not get_settings().upbit_configured,
        reason="UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY not set - BLOCKED, see docs/UPBIT_NOTES.md",
    ),
]


@pytest.mark.asyncio
async def test_real_upbit_list_orders_authenticates() -> None:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.upbit_rest_base_url, timeout=10.0) as client:
        auth = UpbitAuth(settings.upbit_access_key, settings.upbit_secret_key)
        orders = UpbitOrderClient(client, auth)

        result = await orders.list_orders(market="KRW-BTC", state="wait")
        assert isinstance(result, list)
