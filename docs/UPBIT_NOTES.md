# Upbit Public API Notes (P7)

Upbit's ticker/trade/orderbook/candle market data is fully public - no API
key needed anywhere in this phase. `UPBIT_ACCESS_KEY`/`UPBIT_SECRET_KEY` in
`.env.example` are for later, authenticated phases only (account balance,
order placement) and this phase doesn't read them.

## What was verified vs. assumed

`docs.upbit.com` is blocked by this sandbox's outbound egress policy (and so
is `wss://api.upbit.com` itself - confirmed with a direct connection
attempt, which the proxy rejected with a 403, the same "not on the
allowlist" signature seen for `developers.tossinvest.com` in P5). So the
implementation was built the same way P3/P5 handled a blocked primary
source: verify what's checkable from a reachable secondary source, and be
explicit about what wasn't independently confirmed.

**Verified** against `sharebook-kr/pyupbit` (a long-standing, widely-used
open-source Upbit client) on GitHub:

- WebSocket URL: `wss://api.upbit.com/websocket/v1`
- Subscribe frame shape: a JSON array of
  `[{"ticket": ...}, {"type": ..., "codes": [...]}, ...]`
- REST orderbook field names (via the library's documented REST response
  example): `market`, `timestamp`, `total_ask_size`, `total_bid_size`,
  `orderbook_units[].{ask_price, bid_price, ask_size, bid_size}` - note the
  REST payload uses `market` for the symbol field, while everything below
  describes the **WebSocket** payload, which uses `code` instead.
- `GET /v1/market/all` (P9's KRW universe): endpoint path, the `isDetails`
  query param, and the `market` response field - via `pyupbit`'s
  `get_tickers()`, which filters this same field by prefix
  (`x['market'].startswith(fiat)`) exactly like
  `UpbitRestClient.get_krw_market_universe()` does.

**Not independently verified this way** (no reachable source showed a raw
WS response payload) - these are long-stable, extremely widely-documented
Upbit conventions used with high confidence, but re-check against a real
payload before depending on them for anything money-moving:

- WS trade fields: `code`, `trade_price`, `trade_volume`, `ask_bid`
  (`"ASK"`/`"BID"` - the *taker's* side), `trade_timestamp` (epoch ms).
- WS orderbook fields: same shape as the verified REST example, but with
  `code` instead of `market`.
- WS ticker fields: `code`, `trade_price`, `acc_trade_volume_24h`,
  `trade_timestamp`.
- REST candle endpoint `GET /v1/candles/minutes/{unit}` fields:
  `market`, `candle_date_time_utc`, `opening_price`, `high_price`,
  `low_price`, `trade_price`, `candle_acc_trade_volume`.
- Error envelope: `{"error": {"name": ..., "message": ...}}`.

## P15: authenticated order placement/cancel/status

`UPBIT_ACCESS_KEY`/`UPBIT_SECRET_KEY` unlock `app/integrations/upbit/auth.py`
and `orders.py` - place/cancel/status on real orders, gated by
`LIVE_TRADING` the same way `app/integrations/toss/execution.py` gates Toss
(see docs/MASTER_SPEC.md section A). Verified against the same
`sharebook-kr/pyupbit` source as the public endpoints above (`docs.upbit.com`
is still blocked):

- Auth: every authenticated request carries `Authorization: Bearer <jwt>`.
  The JWT payload is `{access_key, nonce}` plus, when the request has
  parameters, `{query_hash: sha512(urlencode(params, doseq=True) with
  "%5B%5D=" -> "[]=" ), query_hash_alg: "SHA512"}`, signed HS256 with the
  secret key.
- `POST /v1/orders` (place): `{market, side: "bid"|"ask", ord_type:
  "limit"|"price"|"market", volume?, price?}` -> `{uuid, state, ...}`.
- `DELETE /v1/order` (cancel) and `GET /v1/order` (status): `{uuid}`.
- `GET /v1/orders` (list, used for reconciliation): `{market, state, page,
  limit, order_by}`. `state` is one of `wait`/`watch` (open), `done`
  (filled), `cancel` (cancelled).

**A real behavioral question this sandbox could not settle**: pyupbit's own
GET/DELETE calls pass their parameters via `requests`' `data=` (a request
body), even though the JWT's `query_hash` is computed as if they were a URL
query string. `app/integrations/upbit/orders.py` sends them as an actual
URL query string instead - the conventional place for GET/DELETE
parameters, and what the hash construction is inherently modeling - but
whether Upbit's real server also accepts (or specifically requires)
pyupbit's body-based form was not independently confirmed either way.
Re-check the first real authenticated call against this before trusting it
in STAGING.

**Not verified at all**: a client-supplied idempotency/`identifier` field.
pyupbit's own source has TODO comments acknowledging it isn't implemented.
`app/integrations/upbit/execution.py` does not invent one - see that
module's docstring for what this means for retry safety (short version: a
timed-out `place_order()` call can never be safely retried automatically,
since there's no confirmed way to prove the original didn't already go
through).

## Why there's no WS candle channel here

Upbit's public WebSocket does not offer a real-time candle stream - only
ticker/trade/orderbook. `UpbitRestClient.get_candles()` covers "candle where
appropriate" (docs/MASTER_SPEC.md P7) via REST instead of pretending a WS
channel exists.

## Re-verifying once this sandbox (or a real machine) can reach Upbit

```
cd backend
source .venv/bin/activate
python -m pytest -q -m P7
```

The real-connection test in `tests/backend/test_upbit_integration.py` is
currently skipped with a network-egress reason (not a missing-credentials
reason, since none are needed) - it will run for real once the host running
it can actually reach `api.upbit.com`.
