"""Toss Securities OpenAPI REST client (P5 read-only account access, P15
order placement/modification/cancellation).

Endpoint paths and the request/response envelope were verified against the
reference client implementation (see docs/TOSS_SETUP.md for how and
where) - not guessed:

- Every response body wraps its payload as `{"result": ...}`.
- Error responses are parsed in the same priority order that reference
  client uses: code from `error.code` -> `code` -> `error` (as a string);
  message from `error.message` -> `message` -> `error_description`;
  request id from the `x-request-id` header, falling back to
  `error.requestId`.
- Every account-scoped endpoint (`get_holdings`, `get_orders`,
  `get_buying_power`, and every order endpoint below) sends `accountSeq` as
  the `X-Tossinvest-Account` HTTP **header**, not a query parameter. P5's
  original implementation sent it as a query param - that was verified only
  against the reference client's *method signatures*, which don't show
  parameter placement. P15 re-verified this against the same repo's
  generated OpenAPI TypeScript types (a more precise, machine-derived
  source), which show `header: {"X-Tossinvest-Account": ...}` on every
  account-scoped operation - so this was a real bug in P5, fixed here.
- Order placement (`create_order`) supports a caller-supplied
  `clientOrderId`; the OpenAPI schema documents `POST /api/v1/orders`
  returning `409` when a `clientOrderId` is reused - Toss's own
  idempotency-detection signal (see `TossDuplicateOrderError` and
  docs/TOSS_SETUP.md). What the schema does **not** expose: `clientOrderId`
  on the `Order` objects returned by `get_order`/`get_orders` - so an order
  can't be looked up by idempotency key after creation, only at creation
  time. Reconciliation (see app/integrations/toss/execution.py) has to fall
  back to matching by symbol/side/quantity/price instead.

Field names *inside* each endpoint's `result` payload beyond what's
documented above were not independently verified for every field (the
sandbox this was built in can't reach the official docs portal) - see
docs/TOSS_SETUP.md for the exact per-endpoint verification notes. Callers
get the raw `result` dict/list rather than a fully-typed schema.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.integrations.toss.auth import TossAuth
from app.integrations.toss.errors import TossApiError, TossDuplicateOrderError, TossRateLimitError


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

    # -- read-only account access (P5) ---------------------------------

    async def get_accounts(self) -> Any:
        return await self._request("GET", "/api/v1/accounts")

    async def get_holdings(self, account_seq: str) -> Any:
        return await self._request("GET", "/api/v1/holdings", account_seq=account_seq)

    async def get_orders(self, account_seq: str, status: str | None = None) -> Any:
        params: dict[str, str] = {}
        if status is not None:
            params["status"] = status
        return await self._request("GET", "/api/v1/orders", account_seq=account_seq, params=params)

    async def get_buying_power(self, account_seq: str, currency: str = "KRW") -> Any:
        return await self._request(
            "GET", "/api/v1/buying-power", account_seq=account_seq, params={"currency": currency}
        )

    # -- order placement/modification/cancellation (P15) -----------------

    async def create_order(
        self,
        account_seq: str,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quantity: str,
        price: str | None = None,
        client_order_id: str | None = None,
        time_in_force: str | None = None,
        confirm_high_value_order: bool | None = None,
    ) -> Any:
        body: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "quantity": quantity,
        }
        if price is not None:
            body["price"] = price
        if client_order_id is not None:
            body["clientOrderId"] = client_order_id
        if time_in_force is not None:
            body["timeInForce"] = time_in_force
        if confirm_high_value_order is not None:
            body["confirmHighValueOrder"] = confirm_high_value_order
        return await self._request("POST", "/api/v1/orders", account_seq=account_seq, json_body=body)

    async def get_order(self, account_seq: str, order_id: str) -> Any:
        return await self._request("GET", f"/api/v1/orders/{order_id}", account_seq=account_seq)

    async def modify_order(
        self, account_seq: str, order_id: str, *, order_type: str, quantity: str, price: str | None = None
    ) -> Any:
        body: dict[str, Any] = {"orderType": order_type, "quantity": quantity}
        if price is not None:
            body["price"] = price
        return await self._request(
            "POST", f"/api/v1/orders/{order_id}/modify", account_seq=account_seq, json_body=body
        )

    async def cancel_order(self, account_seq: str, order_id: str) -> Any:
        return await self._request(
            "POST", f"/api/v1/orders/{order_id}/cancel", account_seq=account_seq, json_body={}
        )

    # -- transport --------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        account_seq: str | None = None,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        token = await self._auth.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        if account_seq is not None:
            headers["X-Tossinvest-Account"] = str(account_seq)

        attempt = 0
        while True:
            response = await self._client.request(
                method, path, params=params, json=json_body, headers=headers
            )
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

        if response.status_code == 429:
            error_cls: type[TossApiError] = TossRateLimitError
        elif response.status_code == 409:
            error_cls = TossDuplicateOrderError
        else:
            error_cls = TossApiError
        return error_cls(response.status_code, code, message, request_id)
