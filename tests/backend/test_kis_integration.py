"""P3 acceptance: 'real connection if credentials available, otherwise BLOCKED'.

No mocking here - this is the one place that's supposed to prove the KIS
integration talks to KIS's real servers. Skipped (not faked) when
KIS_APP_KEY/KIS_APP_SECRET aren't set, which is the honest state of this
repository until a user provisions real credentials (see docs/KIS_SETUP.md).
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import get_settings
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.rest_client import KisRestClient

pytestmark = [
    pytest.mark.P3,
    pytest.mark.skipif(
        not get_settings().kis_configured,
        reason="KIS_APP_KEY / KIS_APP_SECRET not set - BLOCKED, see docs/KIS_SETUP.md",
    ),
]


@pytest.mark.asyncio
async def test_real_kis_access_token_issuance() -> None:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.kis_rest_base_url, timeout=10.0) as client:
        auth = KisAuth(client=client, settings=settings)
        token = await auth.get_access_token()
        assert token


@pytest.mark.asyncio
async def test_real_kis_quote_for_samsung_electronics() -> None:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.kis_rest_base_url, timeout=10.0) as client:
        auth = KisAuth(client=client, settings=settings)
        rest = KisRestClient(client, auth)
        quote = await rest.get_quote("005930")  # 삼성전자
        assert quote.price > 0


@pytest.mark.asyncio
async def test_real_kis_daily_prices_for_samsung_electronics() -> None:
    """P23's get_daily_prices() field layout (inquire-daily-itemchartprice)
    was never independently verified against a live payload - this is that
    verification. If this fails, fix the field names/response shape in
    rest_client.py's get_daily_prices()/_to_daily_candle() to match what
    KIS actually returns, not the other way around."""
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.kis_rest_base_url, timeout=10.0) as client:
        auth = KisAuth(client=client, settings=settings)
        rest = KisRestClient(client, auth)

        end_date = datetime.now(UTC).strftime("%Y%m%d")
        start_date = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y%m%d")

        candles = await rest.get_daily_prices("005930", start_date, end_date)

        assert len(candles) > 0
        assert all(c.close > 0 for c in candles)
        assert all(c.high >= c.low for c in candles)
        # chronological (oldest first), per this method's documented contract
        assert candles == sorted(candles, key=lambda c: c.open_time)
