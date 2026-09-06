"""P12 acceptance: real connection when credentials exist, otherwise BLOCKED.

No mocking here. Unlike KIS/Toss (app-only credentials, see
test_toss_integration.py), Kakao Login's authorization_code grant needs a
real user's browser consent to obtain the first token pair at all - there is
no way to automate that step. So this test is additionally gated on
KAKAO_TEST_REFRESH_TOKEN: a refresh token obtained once by hand through the
real Kakao Login flow (see docs/KAKAO_SETUP.md), used here only to prove
`refresh()` and `get_user_id()` talk to Kakao's real servers correctly -
never to fake an end-to-end login this sandbox cannot perform.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import get_settings
from app.integrations.kakao.auth import KakaoAuth, KakaoTokens

pytestmark = [
    pytest.mark.P12,
    pytest.mark.skipif(
        not (get_settings().kakao_configured and get_settings().kakao_test_refresh_token),
        reason=(
            "KAKAO_CLIENT_ID/KAKAO_REDIRECT_URI/KAKAO_TEST_REFRESH_TOKEN not set - "
            "BLOCKED, see docs/KAKAO_SETUP.md"
        ),
    ),
]


@pytest.mark.asyncio
async def test_real_kakao_refresh_and_user_id_lookup() -> None:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        auth = KakaoAuth(client=client, settings=settings)
        previous = KakaoTokens(
            access_token="",
            refresh_token=settings.kakao_test_refresh_token,
            access_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            refresh_expires_at=datetime.now(UTC) + timedelta(days=60),
        )
        refreshed = await auth.refresh(previous)
        assert refreshed.access_token

        user_id = await auth.get_user_id(refreshed.access_token)
        assert user_id
