"""Kakao Login HTTP API (P21).

Closes the gap `app/api/approvals.py` has flagged since P13: the frontend
had a real OAuth backend (P12's `KakaoAuth`/`KakaoTokenStore`) but no HTTP
route a browser redirect could actually hit, so `ApprovalPage` could only
show "카카오 로그인이 필요합니다" with no way to get past it.

Two endpoints mirror the standard OAuth2 authorization-code redirect dance:

- `GET /api/auth/kakao/login-url` mints a random `state` nonce, stores it in
  Redis with a short TTL, and returns the Kakao consent-screen URL carrying
  that `state` - the frontend redirects the browser there.
- `POST /api/auth/kakao/callback` is called by the frontend after Kakao
  redirects back with `?code=...&state=...`. The `state` must match a nonce
  this service actually issued and not yet consumed (get-and-delete, so a
  replayed callback fails the same way a reused approval token does) -
  otherwise this is a CSRF-able "log the attacker's Kakao session into the
  victim's browser" endpoint.

`user_id`: this application has no separate user registry (a `KakaoAccount`
row's own `user_id` field is documented as "not guaranteed to coincide"
with `kakao_user_id`, but nothing else in this single-user system ever
allocates one) - the first real login uses the Kakao numeric id itself as
`user_id`, which is the honest choice when there is no other identity
source to draw from.

The frontend keeps `user_id` in `localStorage` and sends it back as
`X-User-Id` on approval requests (see `frontend/src/api/client.ts`) rather
than a server-side session cookie - this endpoint completes that existing
design rather than replacing it with a different one.
"""

from __future__ import annotations

import secrets

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings
from app.db.redis_client import get_redis
from app.db.session import session_scope
from app.integrations.kakao.auth import KakaoAuth
from app.integrations.kakao.errors import KakaoAuthError, KakaoNotConfiguredError
from app.integrations.kakao.token_store import KakaoTokenStore

router = APIRouter(prefix="/api/auth/kakao", tags=["auth"])

_STATE_KEY_PREFIX = "kakao_oauth_state:"


class LoginUrlResponse(BaseModel):
    authorize_url: str


class CallbackRequest(BaseModel):
    code: str
    state: str


class CallbackResponse(BaseModel):
    user_id: str


@router.get("/login-url", response_model=LoginUrlResponse)
async def get_login_url() -> LoginUrlResponse:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        auth = KakaoAuth(client=client, settings=settings)
        try:
            state = secrets.token_urlsafe(32)
            redis = get_redis()
            await redis.set(
                f"{_STATE_KEY_PREFIX}{state}", "1", ex=settings.kakao_oauth_state_ttl_seconds
            )
            authorize_url = auth.authorize_url(state=state)
        except KakaoNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return LoginUrlResponse(authorize_url=authorize_url)


@router.post("/callback", response_model=CallbackResponse)
async def kakao_callback(body: CallbackRequest) -> CallbackResponse:
    redis = get_redis()
    state_key = f"{_STATE_KEY_PREFIX}{body.state}"
    # get-and-delete: a state is redeemable exactly once, same replay
    # protection approval tokens get (app/approval/tokens.py).
    consumed = await redis.getdel(state_key)
    if consumed is None:
        raise HTTPException(status_code=410, detail="login state is invalid or already used")

    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        auth = KakaoAuth(client=client, settings=settings)
        try:
            tokens = await auth.exchange_code(body.code)
            kakao_user_id = await auth.get_user_id(tokens.access_token)
        except KakaoNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except KakaoAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        async with session_scope() as session:
            store = KakaoTokenStore(session, auth)
            await store.save(user_id=kakao_user_id, kakao_user_id=kakao_user_id, tokens=tokens)

    return CallbackResponse(user_id=kakao_user_id)
