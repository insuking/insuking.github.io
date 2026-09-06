"""Upbit authenticated order endpoints (P15): place/cancel/status/list.

Verified against `sharebook-kr/pyupbit`'s `Upbit` class (see auth.py's
module docstring for why this source, since `docs.upbit.com` is blocked):

- `POST /v1/orders` (place): body `{market, side, ord_type, volume?, price?}`
  - `side`: `"bid"` (buy) / `"ask"` (sell).
  - `ord_type`: `"limit"` (needs `price` + `volume`), `"price"` (market buy
    by KRW amount - needs `price` only), `"market"` (market sell by
    quantity - needs `volume` only).
- `DELETE /v1/order` (cancel): `{uuid}`.
- `GET /v1/order` (status): `{uuid}`.
- `GET /v1/orders` (list, for reconciliation): `{market, state, page,
  limit, order_by}`.

One deviation from pyupbit's own code, called out explicitly: pyupbit sends
GET/DELETE parameters via `requests`' `data=` (a request body) rather than
the URL query string, even though the JWT's `query_hash` is computed by
URL-encoding those same parameters as if they were a query string. This
client sends them as an actual URL query string instead - the
HTTP-conventional place for GET/DELETE parameters, and what the query-hash
encoding is inherently modeling. Whether Upbit's real server also accepts
(or requires) pyupbit's body-based form was **not** independently verified
either way - re-check against a real response before assuming this is
exactly right.

Not independently verified: `identifier` (a client-supplied idempotency
field some exchanges' order APIs expose) - pyupbit's own source has TODO
comments acknowledging it doesn't implement one, so this client doesn't
send one either rather than guessing at an unconfirmed field name. See
app/integrations/upbit/execution.py for how idempotency is handled without
it.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.integrations.upbit.auth import UpbitAuth
from app.integrations.upbit.errors import UpbitApiError


class UpbitOrderClient:
    def __init__(self, client: httpx.AsyncClient, auth: UpbitAuth) -> None:
        self._client = client
        self._auth = auth

    async def place_order(
        self,
        *,
        market: str,
        side: str,
        ord_type: str,
        volume: str | None = None,
        price: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, object] = {"market": market, "side": side, "ord_type": ord_type}
        if volume is not None:
            body["volume"] = volume
        if price is not None:
            body["price"] = price
        headers = self._auth.build_headers(body)
        response = await self._client.post("/v1/orders", json=body, headers=headers)
        return self._parse(response)

    async def cancel_order(self, order_uuid: str) -> dict[str, Any]:
        params: dict[str, str] = {"uuid": order_uuid}
        headers = self._auth.build_headers(params)
        response = await self._client.delete("/v1/order", params=params, headers=headers)
        return self._parse(response)

    async def get_order(self, order_uuid: str) -> dict[str, Any]:
        params: dict[str, str] = {"uuid": order_uuid}
        headers = self._auth.build_headers(params)
        response = await self._client.get("/v1/order", params=params, headers=headers)
        return self._parse(response)

    async def list_orders(
        self, *, market: str, state: str = "wait", page: int = 1, limit: int = 100
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "market": market,
            "state": state,
            "page": str(page),
            "limit": str(limit),
            "order_by": "desc",
        }
        headers = self._auth.build_headers(params)
        response = await self._client.get("/v1/orders", params=params, headers=headers)
        result = self._parse(response)
        return result if isinstance(result, list) else []

    def _parse(self, response: httpx.Response) -> Any:
        if response.is_error:
            try:
                body = response.json()
            except ValueError:
                body = {}
            error = body.get("error") if isinstance(body.get("error"), dict) else {}
            raise UpbitApiError(response.status_code, error.get("name"), error.get("message"))
        return response.json()
