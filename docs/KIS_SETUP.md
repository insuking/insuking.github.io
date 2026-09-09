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

`KisRestClient.get_daily_prices()` (P23, `inquire-daily-itemchartprice`)
carried the same caveat one level further when first written - the field
names/response shape weren't independently verified (the docs portal and
the GitHub sample repo were both unreachable at the time). **Update, real
credentials configured (2026-09)**: a real docker-compose run got a
successful response and parsed real daily candles for the first two
symbols in `scripts/scan_stocks.py`'s default list before hitting a rate
limit (see "Rate limit" below) - real evidence the field layout is
correct, not yet a full multi-symbol/multi-day confirmation. If a future
run finds a field mismatch, `tests/backend/test_kis_rest_client.py` and
`rest_client.py`'s `_to_daily_candle()` are where to fix it.

## Rate limit

Confirmed by that same real run: unthrottled sequential `get_daily_prices()`
calls tripped KIS's real per-second limit on the third request - HTTP 500
with `{"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를
초과하였습니다"}`. `KisRestClient` now throttles every request to
`max_requests_per_second` (default 2/sec - a conservative starting point,
not a number KIS has published) and retries an `EGW00201` response with
backoff instead of surfacing it as a hard failure. Tighten the default
further if `EGW00201` still appears in practice, or raise it once a longer
real run shows headroom.

## KOSPI/KOSDAQ index benchmark

`KisRestClient.get_index_daily_prices(index_code, start_date, end_date)`
fetches real index candles (KOSPI = `KOSPI_INDEX_CODE` = `"0001"`, KOSDAQ =
`KOSDAQ_INDEX_CODE` = `"1001"`). It first tried reusing
`get_daily_prices()`'s `inquire-daily-itemchartprice` endpoint with
`FID_COND_MRKT_DIV_CODE="U"` - **a real docker-compose run proved that
wrong**: KIS returned `200 {"rt_cd": "2", "msg_cd": "OPSQ2001", "msg1":
"ERROR INVALID FID_COND_MRKT_DIV_CODE"}`, since that endpoint only accepts
stock/ETF/ETN division codes. Once outbound web access let this project
check `github.com/koreainvestment/open-trading-api`'s own sample code
(`examples_llm/domestic_stock/inquire_daily_indexchartprice/`), it was
confirmed indices are a **separate endpoint**,
`inquire-daily-indexchartprice` (tr_id `FHKUP03500100`), whose daily rows
use `bstp_nmix_*` (업종지수) field names instead of a stock row's `stck_*`
fields. `rest_client.py` now calls that endpoint with a dedicated
`_to_daily_index_candle()` parser. Still not independently confirmed
against a live response from this project's own credentials - only
against KIS's public sample code.

`scripts/scan_stocks.py` calls this for its KOSPI benchmark and falls back
to a flat placeholder (with a printed warning) if it raises. The next real
docker-compose run against this method is the actual verification: if it
succeeds, this note should say so the same way the `get_daily_prices()`
note above does; if it still raises `KisApiError`/`KeyError`, fix
`get_index_daily_prices()`/`_to_daily_index_candle()` in `rest_client.py`
from the real error.
