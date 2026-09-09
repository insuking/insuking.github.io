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

`KisRestClient.get_daily_prices_with_name()` reuses that same call
(no extra round trip) to also return the Korean stock name from
`output1.hts_kor_isnm`, confirmed against KIS's public sample repo but not
yet against a live response from this project's own credentials.
`scripts/scan_stocks.py` prints it next to each symbol when available.

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
`_to_daily_index_candle()` parser.

**Update, confirmed by a real docker-compose run (2026-09)**: the
corrected endpoint works - `scripts/scan_stocks.py` printed "Using real
KOSPI index benchmark (50 candles)." and scored real relative-strength
numbers against it. `scripts/scan_stocks.py` still falls back to a flat
placeholder benchmark (with a printed warning) if this call ever raises,
as a safety net, but that path is no longer expected to trigger in
practice.

## Order placement (P29) - real money, read this before touching it

`app/integrations/kis/orders.py` (`KisOrderClient`) and
`app/integrations/kis/execution.py` (`KisExecutionProvider`) implement
`order-cash` (place) and `order-rvsecncl` (cancel) - the first KIS
endpoints in this project that can move real money. Field layout was
verified more carefully than any earlier KIS endpoint: tr_ids
(`TTTC0012U`/`TTTC0011U` real buy/sell, `VTTC0012U`/`VTTC0011U` paper)
and every request body field were cross-checked across three separate
fetches of `koreainvestment/open-trading-api`'s own sample code, not a
single source - see `orders.py`'s own module docstring for the full
per-field provenance.

**Two independent safety switches, both defaulting to the safe side**,
matching the master spec's "실전/모의 환경 전환" and "실전 신규매수" both
being P0급 오류 categories that must never happen by accident:

1. `LIVE_TRADING` (existing, shared with Toss/Upbit) - `false` by
   default. Every mutating method on `KisExecutionProvider` refuses to
   run at all, before any network call, unless this is explicitly `true`.
2. `KIS_PAPER_TRADING` (new, KIS-specific) - `true` by default. Selects
   the paper (모의투자) tr_ids instead of the real ones. Unlike
   `KIS_REST_BASE_URL`, which just points at a different KIS host, the
   tr_id is baked into every order request body - so this needed its own
   explicit switch rather than being inferred from the URL. Getting real
   order routing requires deliberately changing **both** settings from
   their defaults, not one.

**What is NOT built yet**: `reconcile_order()` is not implemented - it
always raises `KisReconciliationNotSupportedError`. Toss/Upbit's versions
do best-effort matching against an order-listing endpoint this project
had already verified in an earlier phase; KIS's natural equivalent
(`inquire-daily-ccld`, 일별주문체결조회) needs mandatory pagination
tokens and an account-type filter this project hasn't confirmed real
values for, and its response field names for an individual fill were
never independently confirmed either. Guessing at both the request *and*
response shape at once for the one endpoint whose job is "tell me what
actually happened to a real order" was judged a worse trade than admitting
the gap - an order left `UNKNOWN` after a timeout must be checked by hand
in the KIS HTS/app until this is built for real.

**Update (P29 continuation)**: the approval -> execution bridge described
above as missing now exists - `app/approval/execution.py`'s
`execute_approved_recommendation()` (broker-agnostic) plus
`gather_kis_revalidation_input()` (KIS-specific), wired into
`POST /api/approvals/{token}/decide` (`app/api/approvals.py`). A human's
APPROVE/APPROVE_WITH_AMOUNT_CHANGE decision on a `STOCK` recommendation
now re-runs P14's `revalidate()` against a fresh KIS quote/candles/risk
state and, only if still `VALID`, calls `KisExecutionProvider.place_order()`
for real (subject to the two safety switches above, both of which still
default to safe). Toss/Upbit (P15) still have the gap described above -
this bridge is broker-agnostic by construction (it takes a `place_order`
callable, not a hardcoded provider) but nothing has built their own
`gather_*_revalidation_input()` yet, so a CRYPTO recommendation's APPROVE
still only ever produces the APPROVED/REJECTED decision, same as before.
What this bridge still does *not* do: track a placed order to a real fill
or open a `Position` from it (no live-broker fill poller exists yet), or
re-check live buying power before sizing (reuses the recommendation's
already-computed `expected_max_loss` - see `execution.py`'s own module
docstring for both).

**No automated real-connection test places, modifies, or cancels a real
order** - not even against 모의투자. Unlike Upbit's real-connection test
(`test_upbit_execution_integration.py`), which calls a genuinely
read-only `list_orders` endpoint to prove its auth signing works without
risking an order, this project has no verified read-only KIS endpoint in
the same auth family that isn't itself an order mutation - and KIS's
Bearer-token auth (`/oauth2/tokenP`) is already proven working for real
by every other KIS endpoint in this project (`get_quote`,
`get_daily_prices`, `get_index_daily_prices`, `get_investor_trend` all
ran successfully against real KIS servers earlier in this project's
history). Re-proving the same auth mechanism by risking a real order was
judged not worth it. **If you want to verify order placement for real,
do it manually**: set `KIS_PAPER_TRADING=true` (paper trading, real
KIS servers, no real money) and call `KisOrderClient.place_order()` by
hand for one small paper order before ever considering
`KIS_PAPER_TRADING=false`.

## Investor flow (외국인/기관 순매수) - P25

`KisRestClient.get_investor_trend(symbol)` calls `inquire-investor` (tr_id
`FHKST01010900`) for daily foreign (외국인) and institutional (기관)
net-buy share counts - `frgn_ntby_qty`/`orgn_ntby_qty`, confirmed against
KIS's public sample repo (`examples_llm/domestic_stock/inquire_investor/`)
but not yet against a live response from this project's own credentials.
Unlike the daily-price endpoints it takes no date range and returns a
flat `output` array (not `output1`/`output2`).

This does **not** cover program-trading (프로그램매매) net flow - a
separate KIS feed this project hasn't touched - so
`app/stock_radar/scoring.py`'s `institutional_flow` factor (12pt) is a
partial, honestly-labeled implementation of the master spec's 19pt
"외국인/기관/프로그램 수급" category, not the full thing.
`scripts/scan_stocks.py`'s scan now fetches this per symbol (one extra
throttled call each) and feeds it into scoring automatically - when it
succeeds, scores show up to 77/77 instead of 65/65 (`institutional_flow`
factor lines in the output); if `get_investor_trend()` raises for a
symbol, that symbol is simply scored without the flow factor (same
65-point ceiling as before P25), not a crashed scan.
