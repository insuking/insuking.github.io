"""Toss Securities OpenAPI authentication (P5).

OAuth2 client_credentials grant, verified against the reference client
implementation (see docs/TOSS_SETUP.md for the source): `POST /oauth2/token`
with `grant_type`, `client_id`, `client_secret` in the body, returning
`access_token` / `token_type` / `expires_in`. Refreshed 30 seconds before
the stated expiry, matching that reference client's skew.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.core.config import Settings, get_settings
from app.integrations.toss.errors import TossAuthError, TossNotConfiguredError

_EXPIRY_SKEW = timedelta(seconds=30)


@dataclass
class _CachedToken:
    value: str
    expires_at: datetime


class TossAuth:
    def __init__(self, client: httpx.AsyncClient, settings: Settings | None = None) -> None:
        self._client = client
        self.settings = settings or get_settings()
        self._token: _CachedToken | None = None

    def _require_configured(self) -> None:
        if not self.settings.toss_configured:
            raise TossNotConfiguredError(
                "TOSS_CLIENT_ID / TOSS_CLIENT_SECRET are not set - see docs/TOSS_SETUP.md"
            )

    async def get_access_token(self) -> str:
        self._require_configured()
        if self._token and self._token.expires_at > datetime.now(UTC):
            return self._token.value

        response = await self._client.post(
            "/oauth2/token",
            json={
                "grant_type": "client_credentials",
                "client_id": self.settings.toss_client_id,
                "client_secret": self.settings.toss_client_secret,
            },
        )
        body = response.json()
        token = body.get("access_token")
        expires_in = body.get("expires_in")
        if response.status_code != 200 or not token or not expires_in:
            raise TossAuthError(f"Toss token issuance failed: {response.status_code} {body}")

        self._token = _CachedToken(
            value=token,
            expires_at=datetime.now(UTC) + timedelta(seconds=int(expires_in)) - _EXPIRY_SKEW,
        )
        return self._token.value
