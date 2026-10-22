# Toss Securities Open API Setup

The P5 Toss integration (`backend/app/integrations/toss/`) covers read-only
account access (accounts, holdings, buying power, order history). P15 adds
order placement, modification, and cancellation on top of it. This
repository ships no real credentials; `TOSS_CLIENT_ID`/`TOSS_CLIENT_SECRET`
are empty in `.env.example` and every Toss test that needs a live
connection is skipped (BLOCKED) rather than faked until you provide them.
Order placement is additionally gated by `LIVE_TRADING` (see "Absolute
safety rule" below) - a real Toss credential alone is never enough to place
a real order.

## Where this implementation's contract came from

This sandbox could not reach `developers.tossinvest.com` (blocked by the
session's egress policy), so the endpoint paths, OAuth flow, and error
envelope in `auth.py`/`rest_client.py` were verified against the source of
`nbsp1221/tossinvest-openapi` on GitHub - an SDK whose own README states it
"uses only endpoints published in the official Toss Securities OpenAPI
documentation." What was directly confirmed from that source:

- Base URL: `https://openapi.tossinvest.com`
- OAuth2 client_credentials: `POST /oauth2/token` with
  `{grant_type, client_id, client_secret}`, response
  `{access_token, token_type, expires_in}`.
- Endpoints: `GET /api/v1/accounts`, `/holdings`, `/orders`, `/buying-power`
  (all under the base URL, Bearer-authenticated).
- Every response wraps its payload as `{"result": ...}`.
- Error responses: code from `error.code` -> `code` -> `error` (string);
  message from `error.message` -> `message` -> `error_description`;
  request id from the `x-request-id` header or `error.requestId`.

### Correction found during P15 (account_seq is a header, not a query param)

P5's original verification only had the reference client's *method
signatures* to go on, which don't show where a parameter is actually sent.
P15 re-verified the same repo's **generated OpenAPI TypeScript types**
(`packages/typescript/src/generated/openapi.ts` - machine-derived directly
from the official schema, so more precise than reading method signatures by
eye) and found every account-scoped operation declares `accountSeq` as the
`X-Tossinvest-Account` HTTP header, never a query parameter. P5's
`get_holdings`/`get_orders`/`get_buying_power` sent it as `?accountSeq=...`
- a real bug, now fixed (`TossRestClient._request` sends it as a header for
every account-scoped call, including the new P15 order endpoints).

### P15: order placement/modification/cancellation

Verified from the same generated OpenAPI types file:

- `POST /api/v1/orders` (`create_order`): body
  `{symbol, side, orderType, quantity, price?, clientOrderId?, timeInForce?,
  confirmHighValueOrder?}` -> `{orderId, clientOrderId}`. Documented
  responses include `409` ("중복 요청" / duplicate request) specifically for
  a reused `clientOrderId` - this is Toss's own server-side idempotency
  signal, exposed here as `TossDuplicateOrderError`.
- `GET /api/v1/orders/{orderId}` (`get_order`) and
  `GET /api/v1/orders?status=OPEN|CLOSED&...` (`get_orders`, already in P5)
  return `Order` objects: `{orderId, symbol, side, orderType, timeInForce,
  status, price, quantity, orderAmount, currency, orderedAt, canceledAt,
  execution: {filledQuantity, averageFilledPrice, filledAmount, commission,
  tax, filledAt, settlementDate}}`. `status` is one of `PENDING`,
  `PENDING_CANCEL`, `PENDING_REPLACE`, `PARTIAL_FILLED`, `FILLED`,
  `CANCELED`, `REJECTED`, `CANCEL_REJECTED`, `REPLACE_REJECTED`, `REPLACED`.
  **`clientOrderId` is not one of these fields** - it's only ever returned
  at creation time, never on a listed/fetched order. This matters for
  reconciliation: an order can't be looked up by idempotency key after the
  fact, only matched heuristically by symbol/side/quantity/price (see
  `app/integrations/toss/execution.py`).
- `POST /api/v1/orders/{orderId}/modify` (`modify_order`): body
  `{orderType, quantity, price?}` -> `{orderId}` - a **new** order id for
  the replacement order, per the schema's own description ("정정/취소로
  새로 발급된 주문 식별자. 원주문의 orderId 와 다릅니다").
- `POST /api/v1/orders/{orderId}/cancel` (`cancel_order`): empty body ->
  `{orderId}` (also a new id, same as modify).

What was **not** independently confirmed: the full field schema inside
`get_accounts`/`get_holdings`/`get_buying_power`'s `result` payload beyond
what's documented above, and whether Toss's `409` deduplication actually
returns the *original* order's outcome anywhere retrievable (the schema
doesn't show one) - `TossExecutionProvider` treats a `409` as "reconcile,
don't assume," never as a confirmed success or failure.

## Absolute safety rule (docs/MASTER_SPEC.md section A)

`TossExecutionProvider.place_order()`/`modify_order()`/`cancel_order()`
raise `LiveTradingDisabledError` immediately, before any network call, when
`LIVE_TRADING` is not `true`. This is enforced in code, not just by leaving
credentials blank - even with real, valid Toss credentials configured, no
order reaches Toss's servers unless `LIVE_TRADING=true` is explicitly set.

## 1. Get credentials

Register at the official developer portal
(https://developers.tossinvest.com) to get:

- `client_id`
- `client_secret`

## 2. Configure this project

Copy `.env.example` to `.env` (never commit `.env`) and fill in:

```
TOSS_CLIENT_ID=your_client_id
TOSS_CLIENT_SECRET=your_client_secret
```

## 3. Verifying it end-to-end

Once `.env` has real credentials, the P5 integration test currently skipped
(`tests/backend/test_toss_integration.py`) will run for real instead of
being marked BLOCKED:

```
cd backend
source .venv/bin/activate
python -m pytest -q -m P5
```

That test only exercises read-only endpoints (token issuance, account
list) - it never places an order, even with `LIVE_TRADING=true`, because an
automated test that could place a real trade on a real account is
unacceptable regardless of credentials. Order placement must be verified
manually, once, in STAGING against a demo/paper account (see
docs/MASTER_SPEC.md's DEV/STAGING/PRODUCTION separation) before any real use.

The first real run is also when you should double-check the `result`
payload shapes mentioned above and tighten `rest_client.py` if they differ
from what's assumed.
