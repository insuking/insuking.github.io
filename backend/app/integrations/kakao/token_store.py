"""Kakao token persistence (P12).

Bridges `KakaoAuth`'s stateless OAuth calls to durable storage
(`app.db.models.KakaoAccount`): an access token lives only hours, a refresh
token lives months, and this codebase is a long-running server, so
persisting means a restart doesn't force the user back through the Kakao
consent screen. Every access token this store hands out is guaranteed
unexpired - callers never see or handle expiry themselves.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KakaoAccount
from app.integrations.kakao.auth import KakaoAuth, KakaoTokens

# Refresh a little before the stated expiry so a request in flight doesn't
# race the token becoming invalid mid-call.
_EXPIRY_SKEW_SECONDS = 60


class KakaoTokenStore:
    def __init__(self, session: AsyncSession, auth: KakaoAuth) -> None:
        self._session = session
        self._auth = auth

    async def _get_account(self, user_id: str) -> KakaoAccount | None:
        result = await self._session.execute(select(KakaoAccount).where(KakaoAccount.user_id == user_id))
        return result.scalar_one_or_none()

    async def save(self, user_id: str, kakao_user_id: str, tokens: KakaoTokens) -> None:
        """Persist tokens from a fresh login (or re-login) for `user_id`."""
        account = await self._get_account(user_id)
        now = datetime.now(UTC)
        if account is None:
            account = KakaoAccount(
                user_id=user_id,
                kakao_user_id=kakao_user_id,
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                access_expires_at=tokens.access_expires_at,
                refresh_expires_at=tokens.refresh_expires_at,
                created_at=now,
                updated_at=now,
            )
            self._session.add(account)
        else:
            account.kakao_user_id = kakao_user_id
            account.access_token = tokens.access_token
            account.refresh_token = tokens.refresh_token
            account.access_expires_at = tokens.access_expires_at
            account.refresh_expires_at = tokens.refresh_expires_at
            account.updated_at = now
        await self._session.commit()

    async def get_valid_access_token(self, user_id: str) -> str | None:
        """A currently-valid access token for `user_id`, refreshing first if
        the stored one is expired (or about to be). `None` if this user has
        never completed Kakao Login.
        """
        account = await self._get_account(user_id)
        if account is None:
            return None

        now = datetime.now(UTC)
        if (account.access_expires_at - now).total_seconds() > _EXPIRY_SKEW_SECONDS:
            return account.access_token

        previous = KakaoTokens(
            access_token=account.access_token,
            refresh_token=account.refresh_token,
            access_expires_at=account.access_expires_at,
            refresh_expires_at=account.refresh_expires_at,
        )
        refreshed = await self._auth.refresh(previous)

        account.access_token = refreshed.access_token
        account.refresh_token = refreshed.refresh_token
        account.access_expires_at = refreshed.access_expires_at
        account.refresh_expires_at = refreshed.refresh_expires_at
        account.updated_at = now
        await self._session.commit()
        return refreshed.access_token
