"""P12 acceptance: Kakao token persistence and transparent refresh.

Runs against the real local Postgres (like test_migrations.py) - not
mocked, since what's being proven here is that tokens actually survive in
the database, not that a call was made correctly. The Kakao *auth* endpoint
itself is still mocked via httpx.MockTransport (a real Kakao connection is
covered separately in test_kakao_integration.py) - only the OAuth transport
is faked, the storage layer is real.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete

from app.core.config import Settings
from app.db.models import KakaoAccount
from app.db.session import session_scope
from app.integrations.kakao.auth import KakaoAuth, KakaoTokens
from app.integrations.kakao.token_store import KakaoTokenStore

pytestmark = [pytest.mark.P12, pytest.mark.asyncio]

_TEST_USER_ID = "test-user-kakao-token-store"


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "kakao_client_id": "test-rest-key",
        "kakao_redirect_uri": "https://example.com/callback",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _tokens(**overrides: object) -> KakaoTokens:
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "access_token": "acc-1",
        "refresh_token": "ref-1",
        "access_expires_at": now + timedelta(hours=6),
        "refresh_expires_at": now + timedelta(days=60),
    }
    defaults.update(overrides)
    return KakaoTokens(**defaults)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
async def _cleanup() -> AsyncGenerator[None]:
    yield
    async with session_scope() as session:
        await session.execute(delete(KakaoAccount).where(KakaoAccount.user_id == _TEST_USER_ID))
        await session.commit()


async def test_save_then_get_valid_access_token_round_trips() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("token is not expired - refresh should never be called")

    auth = KakaoAuth(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), settings=_settings())

    async with session_scope() as session:
        store = KakaoTokenStore(session, auth)
        await store.save(_TEST_USER_ID, kakao_user_id="kakao-1", tokens=_tokens())
        token = await store.get_valid_access_token(_TEST_USER_ID)

    assert token == "acc-1"


async def test_save_upserts_by_user_id() -> None:
    auth = KakaoAuth(
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
        settings=_settings(),
    )

    async with session_scope() as session:
        store = KakaoTokenStore(session, auth)
        await store.save(_TEST_USER_ID, kakao_user_id="kakao-1", tokens=_tokens(access_token="first"))
        await store.save(_TEST_USER_ID, kakao_user_id="kakao-1", tokens=_tokens(access_token="second"))

        result = await session.execute(
            KakaoAccount.__table__.select().where(KakaoAccount.user_id == _TEST_USER_ID)
        )
        rows = result.fetchall()

    assert len(rows) == 1
    assert rows[0].access_token == "second"


async def test_get_valid_access_token_returns_none_for_unknown_user() -> None:
    auth = KakaoAuth(
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
        settings=_settings(),
    )
    async with session_scope() as session:
        store = KakaoTokenStore(session, auth)
        token = await store.get_valid_access_token("no-such-user")

    assert token is None


async def test_get_valid_access_token_refreshes_expired_token_and_persists_it() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "refreshed-access",
                "expires_in": 3600,
                "refresh_token": "refreshed-refresh",
                "refresh_token_expires_in": 5184000,
            },
        )

    auth = KakaoAuth(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), settings=_settings())
    expired_tokens = _tokens(access_expires_at=datetime.now(UTC) - timedelta(seconds=1))

    async with session_scope() as session:
        store = KakaoTokenStore(session, auth)
        await store.save(_TEST_USER_ID, kakao_user_id="kakao-1", tokens=expired_tokens)
        token = await store.get_valid_access_token(_TEST_USER_ID)

    assert token == "refreshed-access"
    assert len(calls) == 1

    # Persisted, not just returned in-memory - a fresh session sees the update.
    async with session_scope() as session:
        result = await session.execute(
            KakaoAccount.__table__.select().where(KakaoAccount.user_id == _TEST_USER_ID)
        )
        row = result.fetchone()
    assert row is not None
    assert row.access_token == "refreshed-access"
    assert row.refresh_token == "refreshed-refresh"
