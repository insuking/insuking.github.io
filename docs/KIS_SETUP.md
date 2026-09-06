# KIS (Korea Investment Securities) Open API Setup

The P3 KIS integration (`backend/app/integrations/kis/`) is fully implemented
against the officially documented KIS Open API protocol, but this repository
does not ship real credentials - `KIS_APP_KEY`/`KIS_APP_SECRET` are empty in
`.env.example` and every KIS test that needs a live connection is skipped
(BLOCKED) rather than faked until you provide them.

## 1. Get an account and API keys

1. Open a real or virtual (모의투자) account with Korea Investment
   Securities.
2. Register an application at the KIS Developers portal
   (https://apiportal.koreainvestment.com) to get:
   - `appkey`
   - `appsecret`
3. Note your account number (`계좌번호`), format `XXXXXXXX-XX`.

## 2. Configure this project

Copy `.env.example` to `.env` (never commit `.env`) and fill in:

```
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_ACCOUNT_NO=your_account_number
```

Real domain (`KIS_REST_BASE_URL`) defaults to
`https://openapi.koreainvestment.com:9443` and the WebSocket URL
(`KIS_WS_URL`) to `wss://ops.koreainvestment.com:21000`. KIS also runs a
virtual-trading (모의투자) domain on different hosts/ports if you want to test
against that instead - override both URLs in `.env` if so.

## 3. What becomes available once configured

- `KisAuth.get_access_token()` / `get_ws_approval_key()` - REST bearer token
  and WebSocket approval key, both cached until shortly before expiry.
- `KisRestClient.get_quote(symbol)` - current-price snapshot as a P1 `Quote`.
- `KisWebSocketClient` - subscribes to `H0STCNT0` (real-time trades) and
  `H0STASP0` (real-time orderbook), reconnects with backoff on drop, and
  replays every active subscription after reconnecting.

## 4. Verifying it end-to-end

Once `.env` has real credentials, the P3 integration test that is currently
skipped (see `tests/backend/test_kis_integration.py`) will run for real
against KIS's servers instead of being marked BLOCKED. Run:

```
cd backend
source .venv/bin/activate
python -m pytest -q -m P3
```

and confirm it reports a real quote and at least one real-time message
rather than a skip.

## Field layout note

The WebSocket field orderings in `app/integrations/kis/fields.py` were
pulled from KIS's own official sample code
(`koreainvestment/open-trading-api` on GitHub) rather than guessed. KIS does
not publish a versioned schema guarantee for these fields, so re-verify them
against a real payload the first time you connect with live credentials -
if anything has drifted, `tests/backend/test_kis_parsing.py` is where to fix
the field list.
