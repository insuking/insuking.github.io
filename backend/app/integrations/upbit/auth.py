"""Upbit authenticated-request signing (P15).

Upbit's authenticated REST endpoints (orders, balances) don't use OAuth -
every request carries a JWT in its `Authorization` header, signed with the
account's own secret key. Verified against `sharebook-kr/pyupbit`'s
`Upbit._request_headers()` (a long-standing, widely-used open-source Upbit
client - the same source docs/UPBIT_NOTES.md already used for the public
WebSocket/REST contract in P7), since `docs.upbit.com` is blocked by this
sandbox's egress policy just like it was for P7's public endpoints:

- JWT payload: `{"access_key": <access_key>, "nonce": <fresh uuid4 str>}`,
  plus, only when the request carries query parameters or a body,
  `{"query_hash": <sha512 hex of the urlencoded params>, "query_hash_alg":
  "SHA512"}`. The urlencoding uses `doseq=True` and a specific fix-up
  (`.replace("%5B%5D=", "[]=")`) for array-valued parameters - reproduced
  exactly here since a different encoding produces a different hash and an
  invalid signature.
- Signed with `HS256` using the account's secret key, sent as
  `Authorization: Bearer <jwt>`.

Not independently verified this way (pyupbit doesn't need it, since account
JWTs don't touch the public endpoints P7 already covers): the exact error
envelope authenticated endpoints return on an invalid/expired signature.
`app/integrations/upbit/errors.py`'s `UpbitApiError` (already used for
public endpoints) is reused rather than inventing an unverified shape.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from urllib.parse import urlencode

import jwt


class UpbitAuth:
    def __init__(self, access_key: str, secret_key: str) -> None:
        self._access_key = access_key
        self._secret_key = secret_key

    def build_headers(self, params: Mapping[str, object] | None = None) -> dict[str, str]:
        """Bearer-JWT header for one request. `params` must be exactly the
        query params (GET/DELETE) or body fields (POST) of that request -
        the signature covers them, so a mismatch is an invalid signature at
        the server, not a client-side concern this method can catch.
        """
        payload: dict[str, object] = {
            "access_key": self._access_key,
            "nonce": str(uuid.uuid4()),
        }
        if params:
            encoded = urlencode(params, doseq=True).replace("%5B%5D=", "[]=")
            query_hash = hashlib.sha512(encoded.encode()).hexdigest()
            payload["query_hash"] = query_hash
            payload["query_hash_alg"] = "SHA512"

        token = jwt.encode(payload, self._secret_key, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}
