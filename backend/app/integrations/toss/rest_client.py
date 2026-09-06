"""Toss Securities OpenAPI REST client (P5): read-only account access.

Endpoint paths and the request/response envelope below were verified
against the reference client implementation (see docs/TOSS_SETUP.md for how
and where), not guessed:

- Every response body wraps its payload as `{"result": ...}`.
- Error responses are parsed in the same priority order that reference
  client uses: code from `error.code` -> `code` -> `error` (as a string);
  message from `error.message` -> `message` -> `error_description`;
  request id from the `x-request-id` header, falling back to
  `error.requestId`.
- No order placement here - that's P15 (Execution providers). This phase is
  read-only: accounts, holdings, buying power, order history.

Field names *inside* each endpoint's `result` payload (beyond `accountSeq`,
which the reference client's own method signatures confirm) were not
independently verified, since the sandbox this was built in couldn't reach
the official docs portal - see docs/TOSS_SETUP.md. Callers get the raw
`result` dict/list rather than a fabricated typed schema.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.integrations.toss.auth import TossAuth
from app.integrations.toss.errors import TossApiError, TossRateLimitError


def mask_account_identifier(value: str, visible: int = 4) -> str:
    """Mask all but the last `visible` characters - for logs/UI, never for API calls."""
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]


class TossRestClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        auth: TossAuth,
        max_retries: int = 3,
        base_backoff_seconds: float = 1.0,
    ) -> None:
        self._client = client
        self._auth = auth
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds

    async def get_accounts(self) -> Any:
        return await self._get("/api/v1/accounts")

    async def get_holdings(self, account_seq: str) -> Any:
        return await self._get("/api/v1/holdings", params={"accountSeq": account_seq})

    async def get_orders(self, account_seq: str, status: str | None = None) -> Any:
        params: dict[str, str] = {"accountSeq": account_seq}
        if status is not None:
            params["status"] = status
        return await self._get("/api/v1/orders", params=params)

    async def get_buying_power(self, account_seq: str, currency: str = "KRW") -> Any:
        return await self._get(
            "/api/v1/buying-power", params={"accountSeq": account_seq, "currency": currency}
        )

    async def _get(self, path: str, params: dict[str, str] | None = None) -> Any:
        token = await self._auth.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        attempt = 0
        while True:
            response = await self._client.get(path, params=params, headers=headers)
            if response.status_code == 429 and attempt < self._max_retries:
                attempt += 1
                await asyncio.sleep(self._retry_delay(response, attempt))
                continue
            break

        if response.is_error:
            raise self._build_error(response)
        return response.json().get("result")

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return self._base_backoff * (2 ** (attempt - 1))

    def _build_error(self, response: httpx.Response) -> TossApiError:
        try:
            body = response.json()
        except ValueError:
            body = {}

        error_field = body.get("error")
        error_obj = error_field if isinstance(error_field, dict) else {}

        code = error_obj.get("code") or body.get("code") or (error_field if isinstance(error_field, str) else None)
        message = error_obj.get("message") or body.get("message") or body.get("error_description")
        request_id = response.headers.get("x-request-id") or error_obj.get("requestId")

        error_cls = TossRateLimitError if response.status_code == 429 else TossApiError
        return error_cls(response.status_code, code, message, request_id)
