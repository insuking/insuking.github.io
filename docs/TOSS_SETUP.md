# Toss Securities Open API Setup

The P5 Toss integration (`backend/app/integrations/toss/`) is read-only
(accounts, holdings, buying power, order history) - order placement is P15
(Execution providers). This repository ships no real credentials;
`TOSS_CLIENT_ID`/`TOSS_CLIENT_SECRET` are empty in `.env.example` and every
Toss test that needs a live connection is skipped (BLOCKED) rather than
faked until you provide them.

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
- `accountSeq` identifies an account and is required by `holdings`,
  `orders`, and `buying-power` calls (confirmed by the reference client's
  own method signatures).

What was **not** independently confirmed: the full field schema inside each
endpoint's `result` payload (e.g. what a holding or a buying-power entry
looks like beyond `accountSeq`). `TossRestClient` deliberately returns the
raw `result` value rather than a fabricated typed model for those - verify
the real shape against a live response (or the official docs, once
reachable) before building anything downstream that assumes specific field
names.

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

The first real run is also when you should double-check the `result`
payload shapes mentioned above and tighten `rest_client.py` if they differ
from what's assumed.
