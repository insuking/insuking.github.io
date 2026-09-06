"""P5 acceptance: real connection when credentials exist, otherwise BLOCKED.

No mocking here - this is the one place meant to prove the Toss integration
talks to Toss's real servers. Skipped (not faked) when
TOSS_CLIENT_ID/TOSS_CLIENT_SECRET aren't set, the honest state of this
repository until a user provisions real credentials (see docs/TOSS_SETUP.md).
"""

import httpx
import pytest

from app.core.config import get_settings
from app.integrations.toss.auth import TossAuth
from app.integrations.toss.rest_client import TossRestClient

pytestmark = [
    pytest.mark.P5,
    pytest.mark.skipif(
        not get_settings().toss_configured,
        reason="TOSS_CLIENT_ID / TOSS_CLIENT_SECRET not set - BLOCKED, see docs/TOSS_SETUP.md",
    ),
]


@pytest.mark.asyncio
async def test_real_toss_access_token_issuance() -> None:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.toss_rest_base_url, timeout=10.0) as client:
        auth = TossAuth(client=client, settings=settings)
        token = await auth.get_access_token()
        assert token


@pytest.mark.asyncio
async def test_real_toss_accounts_list() -> None:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.toss_rest_base_url, timeout=10.0) as client:
        auth = TossAuth(client=client, settings=settings)
        rest = TossRestClient(client, auth)
        accounts = await rest.get_accounts()
        assert accounts is not None
