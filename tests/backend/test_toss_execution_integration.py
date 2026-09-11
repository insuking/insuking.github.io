"""P15 acceptance: real connection for the order-management endpoints Toss
execution relies on, when credentials exist - otherwise BLOCKED.

This deliberately does **not** place, modify, or cancel a real order -
`create_order`/`modify_order`/`cancel_order` are never called here,
regardless of `LIVE_TRADING`. An automated test that could place a real
trade on a real account is unacceptable no matter what credentials are
configured (see docs/TOSS_SETUP.md's "Verifying it end-to-end" section).
This only proves `get_orders` (read-only, the same call
`TossExecutionProvider.reconcile_order()` uses) works against Toss's real
servers with the corrected `X-Tossinvest-Account` header (see
docs/TOSS_SETUP.md for the P15 correction).
"""

import httpx
import pytest

from app.core.config import get_settings
from app.integrations.toss.auth import TossAuth
from app.integrations.toss.rest_client import TossRestClient

pytestmark = [
    pytest.mark.P15,
    pytest.mark.skipif(
        not get_settings().toss_configured,
        reason="TOSS_CLIENT_ID / TOSS_CLIENT_SECRET not set - BLOCKED, see docs/TOSS_SETUP.md",
    ),
]


@pytest.mark.asyncio
async def test_real_toss_get_orders_with_account_header() -> None:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.toss_rest_base_url, timeout=10.0) as client:
        auth = TossAuth(client=client, settings=settings)
        rest = TossRestClient(client, auth)

        accounts = await rest.get_accounts()
        assert accounts, "no Toss accounts returned - can't exercise get_orders without one"
        account_seq = accounts[0]["accountSeq"]

        orders = await rest.get_orders(str(account_seq), status="OPEN")
        assert orders is not None
