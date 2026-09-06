"""Kakao Login OAuth2 (P12).

This sandbox's egress policy blocks `developers.kakao.com` directly (same
restriction hit for KIS/Toss in P3/P5), so the contract below was verified
through web-search snippets of Kakao's own official docs
(`developers.kakao.com/docs/latest/en/kakaologin/rest-api` and
`.../kakaotalk-message/rest-api`), cross-checked against multiple
independent search results rather than trusted from a single source. What
was verified this way:

- Authorization code grant: `POST https://kauth.kakao.com/oauth/token`,
  form-urlencoded, `{grant_type: "authorization_code", client_id,
  redirect_uri, code, client_secret?}` -> `{token_type, access_token,
  expires_in, refresh_token, refresh_token_expires_in, scope}`.
- Refresh grant: same endpoint, `{grant_type: "refresh_token", client_id,
  refresh_token, client_secret?}` -> a new `access_token`/`expires_in`
  always, but `refresh_token`/`refresh_token_expires_in` **only when the
  existing refresh token has under one month left** - otherwise the prior
  refresh token is still the valid one and must be kept.
- User id lookup: `GET https://kapi.kakao.com/v2/user/me` with
  `Authorization: Bearer <access_token>` -> `{id, kakao_account, ...}`;
  `id` is Kakao's numeric per-app user id.
- `client_secret` is an optional, separately-toggled app setting for Kakao
  (unlike KIS/Toss where the secret is mandatory) - sent only when
  configured.

Not independently verified: the exact shape of `kakao_account` (email,
profile fields) beyond the top-level `id` - this module doesn't read it,
so no assumption about it is baked in anywhere downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx

from app.core.config import Settings, get_settings
from app.integrations.kakao.errors import KakaoAuthError, KakaoNotConfiguredError

_TOKEN_PATH = "/oauth/token"
_AUTHORIZE_PATH = "/oauth/authorize"
_USER_ME_PATH = "/v2/user/me"


@dataclass
class KakaoTokens:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    scope: str | None = None


def _parse_json(response: httpx.Response) -> dict[str, object]:
    try:
        body = response.json()
    except ValueError as exc:
        raise KakaoAuthError(f"Kakao response was not valid JSON: {response.status_code} {response.text}") from exc
    if not isinstance(body, dict):
        raise KakaoAuthError(f"Unexpected Kakao response shape: {body!r}")
    return body


class KakaoAuth:
    def __init__(self, client: httpx.AsyncClient, settings: Settings | None = None) -> None:
        self._client = client
        self.settings = settings or get_settings()

    def _require_configured(self) -> None:
        if not self.settings.kakao_configured:
            raise KakaoNotConfiguredError(
                "KAKAO_CLIENT_ID / KAKAO_REDIRECT_URI are not set - see docs/KAKAO_SETUP.md"
            )

    def authorize_url(self, state: str | None = None) -> str:
        """URL to send the user's browser to for the Kakao Login consent screen."""
        self._require_configured()
        params = {
            "client_id": self.settings.kakao_client_id,
            "redirect_uri": self.settings.kakao_redirect_uri,
            "response_type": "code",
        }
        if state:
            params["state"] = state
        return f"{self.settings.kakao_auth_base_url}{_AUTHORIZE_PATH}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> KakaoTokens:
        """Exchange an authorization code from the redirect callback for tokens."""
        self._require_configured()
        data = {
            "grant_type": "authorization_code",
            "client_id": self.settings.kakao_client_id,
            "redirect_uri": self.settings.kakao_redirect_uri,
            "code": code,
        }
        if self.settings.kakao_client_secret:
            data["client_secret"] = self.settings.kakao_client_secret

        response = await self._client.post(
            f"{self.settings.kakao_auth_base_url}{_TOKEN_PATH}",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        )
        body = _parse_json(response)
        access_token = body.get("access_token")
        refresh_token = body.get("refresh_token")
        expires_in = body.get("expires_in")
        refresh_expires_in = body.get("refresh_token_expires_in")
        if (
            response.status_code != 200
            or not isinstance(access_token, str)
            or not isinstance(refresh_token, str)
            or not isinstance(expires_in, int)
            or not isinstance(refresh_expires_in, int)
        ):
            raise KakaoAuthError(f"Kakao token issuance failed: {response.status_code} {body}")

        now = datetime.now(UTC)
        scope = body.get("scope")
        return KakaoTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=now + timedelta(seconds=expires_in),
            refresh_expires_at=now + timedelta(seconds=refresh_expires_in),
            scope=scope if isinstance(scope, str) else None,
        )

    async def refresh(self, previous: KakaoTokens) -> KakaoTokens:
        """Refresh an access token. Keeps the prior `refresh_token`/expiry
        unless Kakao issued a new one (see module docstring)."""
        self._require_configured()
        data = {
            "grant_type": "refresh_token",
            "client_id": self.settings.kakao_client_id,
            "refresh_token": previous.refresh_token,
        }
        if self.settings.kakao_client_secret:
            data["client_secret"] = self.settings.kakao_client_secret

        response = await self._client.post(
            f"{self.settings.kakao_auth_base_url}{_TOKEN_PATH}",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        )
        body = _parse_json(response)
        access_token = body.get("access_token")
        expires_in = body.get("expires_in")
        if response.status_code != 200 or not isinstance(access_token, str) or not isinstance(expires_in, int):
            raise KakaoAuthError(f"Kakao token refresh failed: {response.status_code} {body}")

        now = datetime.now(UTC)
        new_refresh_token = body.get("refresh_token")
        refresh_token = new_refresh_token if isinstance(new_refresh_token, str) else previous.refresh_token

        new_refresh_expires_in = body.get("refresh_token_expires_in")
        refresh_expires_at = (
            now + timedelta(seconds=new_refresh_expires_in)
            if isinstance(new_refresh_expires_in, int)
            else previous.refresh_expires_at
        )

        scope = body.get("scope")
        return KakaoTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=now + timedelta(seconds=expires_in),
            refresh_expires_at=refresh_expires_at,
            scope=scope if isinstance(scope, str) else previous.scope,
        )

    async def get_user_id(self, access_token: str) -> str:
        """The caller's Kakao per-app numeric user id, as a string."""
        response = await self._client.get(
            f"{self.settings.kakao_api_base_url}{_USER_ME_PATH}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        body = _parse_json(response)
        user_id = body.get("id")
        if response.status_code != 200 or user_id is None:
            raise KakaoAuthError(f"Kakao user info lookup failed: {response.status_code} {body}")
        return str(user_id)
