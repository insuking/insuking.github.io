"""KIS Open API authentication (P3).

Two distinct credentials are involved:

- REST access token: `POST /oauth2/tokenP` with grant_type=client_credentials,
  appkey/appsecret. Valid ~24h; every REST call needs it as a Bearer header.
- WebSocket approval key: `POST /oauth2/Approval` with grant_type=
  client_credentials, appkey/secretkey. Sent once in the WS subscribe frame,
  not as a header - the socket itself isn't authenticated per-message.

Both are cached in memory and refreshed a safety margin before expiry rather
than on every call, since KIS rate-limits token issuance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import Settings, get_settings
from app.integrations.kis.errors import KisAuthError, KisNotConfiguredError

# Refresh this long before the token's stated expiry so a slow request never
# straddles the boundary and gets rejected mid-call.
_REFRESH_MARGIN = timedelta(minutes=5)


@dataclass
class _CachedToken:
    value: str
    expires_at: datetime


class KisAuth:
    def __init__(self, client: httpx.AsyncClient, settings: Settings | None = None) -> None:
        self._client = client
        self.settings = settings or get_settings()
        self._token: _CachedToken | None = None
        self._approval_key: _CachedToken | None = None

    def _require_configured(self) -> None:
        if not self.settings.kis_configured:
            raise KisNotConfiguredError(
                "KIS_APP_KEY / KIS_APP_SECRET are not set - see docs/KIS_SETUP.md"
            )

    async def get_access_token(self) -> str:
        self._require_configured()
        if self._token and self._token.expires_at > datetime.now(UTC):
            return self._token.value

        response = await self._client.post(
            "/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": self.settings.kis_app_key,
                "appsecret": self.settings.kis_app_secret,
            },
        )
        body = response.json()
        token = body.get("access_token")
        expires_in = body.get("expires_in")
        if response.status_code != 200 or not token or not expires_in:
            raise KisAuthError(f"KIS token issuance failed: {response.status_code} {body}")

        self._token = _CachedToken(
            value=token,
            expires_at=datetime.now(UTC) + timedelta(seconds=int(expires_in)) - _REFRESH_MARGIN,
        )
        return self._token.value

    async def get_ws_approval_key(self) -> str:
        self._require_configured()
        if self._approval_key and self._approval_key.expires_at > datetime.now(UTC):
            return self._approval_key.value

        response = await self._client.post(
            "/oauth2/Approval",
            json={
                "grant_type": "client_credentials",
                "appkey": self.settings.kis_app_key,
                "secretkey": self.settings.kis_app_secret,
            },
        )
        body = response.json()
        approval_key = body.get("approval_key")
        if response.status_code != 200 or not approval_key:
            raise KisAuthError(f"KIS approval key issuance failed: {response.status_code} {body}")

        # KIS documents the approval key as valid for 24h; refreshed with the
        # same safety margin as the REST token rather than a separate value.
        self._approval_key = _CachedToken(
            value=approval_key,
            expires_at=datetime.now(UTC) + timedelta(hours=24) - _REFRESH_MARGIN,
        )
        return self._approval_key.value
