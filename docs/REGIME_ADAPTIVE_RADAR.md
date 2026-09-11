# Regime-Adaptive Radar (P34-P44)

This extends the stock radar from "rank candidates by a single score" to
three additional, independent signals layered on top: how a symbol's
strength interacts with the market's own direction (P34), whether it's
already moved too far to chase (P35), and a final BUY/WATCH/NO_BUY/
NO_TRADE_DAY call that treats "nothing worth buying today" as a normal,
successful outcome rather than an absence to work around (P36) - plus the
real benchmark-candle persistence (P37) that closes the gap that was
causing the 시장 tab's "데이터 없음" for the domestic market, and the
08:20 KST premarket macro check (P38).

## P34 - Market Regime x Relative Strength Interaction Engine

`app/stock_radar/regime_interaction.py`'s `compute_interaction_score()`
scores four situations, kept **out of** the PRE-BREAKOUT score's own
0-65/77 total (see `scoring.py`) and reported as its own separate
`interaction_score`, matching this feature's own dashboard mockups
showing "Radar" and "Market RS" as two different numbers:

1. Market down >=1.5% and the stock still up >=1% -> +2 (STRONG_RELATIVE_STRENGTH)
2. Market down >=1.5% and the stock merely non-negative -> +1 (WEAK_MARKET_RESILIENT)
3. Market down >=1.5% and both foreign+institutional investors net buying today -> +2
4. Yesterday both foreign+institutional net buying, but today the stock
   underperforms the benchmark -> -3 (FLOW_NOT_PERSISTENT)

Persisted per CONFIRMED symbol per `scripts/reconfirm_entries.py` run to
the new `regime_relative_strength` table (`app/stock_radar/
regime_persistence.py`). Benchmark/stock returns reuse data already
fetched for the regime read and the P35 heat score (no extra KIS calls);
investor flow costs one extra `get_investor_trend()` call per CONFIRMED
symbol (the same P25 endpoint `scan_stocks.py` already uses).

## P35 - Overheat / TOO LATE Engine

`app/stock_radar/overheat.py`'s `compute_heat_score()` scores how
extended a candidate already is from 1-day/2-day/5-day return, distance
above the PRE-BREAKOUT signal's own reference price, gap size, and a
smaller volume/ATR-extension bonus, into a 0-100 `heat_score` banded
NORMAL/WARM/HOT/VERY_HOT/TOO_LATE.

**This is wired as a hard gate, not just a display number**:
`app/stock_radar/scan.py`'s `build_confirmed_recommendations()` now
computes a heat score for every CONFIRMED candidate and skips building a
`Recommendation` entirely when the result is TOO_LATE - a symbol scoring
90 on the PRE-BREAKOUT scale is still excluded from the 추천 탭 if it's
already run too far. Every reading (not just the survivors) is persisted
to `overheat_scores` so a later review can see what got filtered.

## P36 - No-Trade Decision Engine + Dynamic Candidate Threshold

`app/stock_radar/decision.py`:
- `dynamic_minimum_score(regime)` - the minimum normalized (0-100) score
  required to be considered at all rises as the regime worsens (80 in
  RISK_ON, 82 in NEUTRAL, 85 in RISK_OFF - see the module's own docstring
  for why only 3 of the requested 5 regime tiers exist today).
- `decide_entry_state(...)` - one symbol's final STRONG_BUY/BUY/WATCH/
  NO_BUY call from its score, P35 heat status, and how many entry
  filters it passed. TOO_LATE always forces NO_BUY regardless of score.
- `decide_daily_state(...)` - the day's overall call, derived from the
  best symbol's own decision: NO_TRADE_DAY exactly when nothing scanned
  today reached at least BUY.

**Now wired**: `scripts/reconfirm_entries.py` calls
`decide_entry_state()` for every CONFIRMED symbol reconfirmed in a run,
picks the best one, calls `decide_daily_state()`, and persists the result
via `app/stock_radar/decision_persistence.py` to a new `daily_decisions`
table - `app/api/dashboard.py`'s `/summary` endpoint surfaces it as
`stock_decision_state`/`stock_decision_reason`/`stock_decision_top_symbol`
/`stock_decision_top_symbol_name`, and the 시장 tab's "오늘의 판정" card
reads it directly.

`decide_entry_state()` needs an entry-filter count; this project never
built the spec's literal 5-filter bank (VWAP/opening-support/RVOL/flow/RS
- those are crypto-radar P4 concepts, not something the stock radar has).
`scripts/reconfirm_entries.py`'s `_entry_filters()` uses an honest proxy
instead: `len(score.positive)` (the PRE-BREAKOUT factors that already
cleared the scoring engine's own "strong signal" bar) out of 7, or 8 when
P25's institutional-flow factor was also scored - real, already-computed
data, not a new fabricated filter bank.

## P37 - Real Benchmark Candle Persistence

Root cause of the 시장 tab showing "데이터 없음" for the domestic market:
nothing in production ever wrote to the generic `candles` table
`app/api/dashboard.py`'s regime read depends on - the KOSPI benchmark
candles `scripts/scan_stocks.py` fetches for its own RS calculation were
used in-memory and discarded, and BTC only ever "worked" because
`seed_demo_data.py`'s demo seed data happened to include `KRW-BTC` bars.

`app/radar/candle_persistence.py`'s `persist_candles()` (delete-then-
insert by symbol/interval/date-range, idempotent on rerun) is now called
from both `scan_stocks.py` (real KOSPI daily candles, symbol `"0001"` -
`KisRestClient.KOSPI_INDEX_CODE`, now `config.py`'s `market_index_symbol`
default) and `scan_crypto.py` (real BTC daily candles via Upbit, kept
separate from the 1-minute candles RVOL/breakout math uses). Both only
persist on a successful real fetch - the flat placeholder fallback used
when a fetch fails is never written, so a real "no data yet" state stays
distinguishable from real data.

## P38 - Daily 08:20 KST Premarket Macro Check

Fetches real S&P500, SOX(필라델피아 반도체지수), VIX, WTI 유가, and
USD/KRW data from Yahoo Finance's public `/v8/finance/chart/{symbol}`
endpoint (no API key needed - same "public, no auth" tier as Upbit's
REST API) via `app/integrations/market_macro/rest_client.py`, classifies
it into `MacroRegime` (RISK_ON/NEUTRAL/RISK_OFF) with a one-line Korean
headline via `app/radar/macro_regime.py`'s `classify_macro_regime()`, and
persists it to a new `macro_snapshots` table
(`app/radar/macro_persistence.py`).

**Advisory only, deliberately not wired into P35/P36's gating**: this
project's standing rule is that the system must never become fully
autonomous - every real-money action still requires explicit human
approval every time. Feeding an unvalidated, un-backtested macro
threshold into P36's automatic NO_TRADE_DAY/TOO_LATE logic would let this
phase silently block legitimate trades. So the reading is surfaced on the
시장 탭's "해외 매크로 (프리마켓 체크)" card - exactly how the original
request framed the 08:20 daily check-in: something a person reviews each
morning, not an automatic filter. The card itself says as much
("참고용 신호입니다..."). Wiring it into `decide_entry_state()`'s scoring
is a natural next step once these thresholds have real trading outcomes
to validate against.

**Scheduling**: `scripts/scheduler.py`'s `run_cycle()` runs
`scripts/scan_macro.py` once per KST calendar date, on the first cycle
whose KST time-of-day is at or after 08:20 - a wall-clock-time job, not
an interval job like the crypto/stock passes (tracked via
`last_macro_run_date`, a `date`, not a timestamp).

**Thresholds are a first, documented pass, not a tuned model** - there is
no backtest harness for macro thresholds yet (see this doc's Known gaps
for the same caveat on P34-P36's own thresholds). Any one of VIX >= 25,
S&P500 <= -1.5%, SOX <= -2.5%, |WTI oil| >= 4%, or USD/KRW >= +1.0%
(KRW weakening) is independently enough to call RISK_OFF; RISK_ON needs
VIX <= 15 AND S&P500 >= +0.5% AND SOX >= +0.5% together (the same
asymmetry P34 already uses - easy to flag caution, hard to declare "all
clear"). A single symbol's fetch failing degrades that one metric to
`None` (never a fabricated 0) rather than aborting the whole snapshot.

**Live-network test status**: like this project's other public-API
integrations, this sandbox's outbound egress is restricted to an
allowlist that does not include query1.finance.yahoo.com - a live call
against the real endpoint has not been exercised from this environment
(confirmed via a direct `curl` returning a proxy `connect_rejected`), so
`app/integrations/market_macro/rest_client.py`'s parsing is unit-tested
against Yahoo's documented chart-API JSON shape instead
(`tests/backend/test_market_macro_rest_client.py`) - the same accepted
pattern this project already used for KIS/Toss/Upbit's own
real-connection tests (P3/P5/P7). Verify against the real endpoint once
deployed somewhere with open egress (a normal Docker Compose host,
unlike this sandboxed dev container, typically has this).

## P40 - Stock Radar Walk-Forward Backtest Harness

The stock-radar equivalent of the crypto radar's own backtest harness
(P10/P24, `app/scan/crypto_backtest.py`) - closes the "the stock radar
has no backtest harness" half of the KPI gap below.
`app/stock_radar/backtest.py`'s `backtest_prebreakout_strategy()` replays
real historical daily candles bar-by-bar through the exact same
production pipeline `scripts/scan_stocks.py`/`scripts/reconfirm_entries.py`
use live - `score_prebreakout()` (P23), `confirm_entry()` (P27),
`compute_heat_score()` (P35, the same hard TOO_LATE gate
`build_confirmed_recommendations()` applies), and `decide_entry_state()`
(P36) - never a separate, simplified copy of the scoring logic. At day
`i`, only `candles[0..i]` are visible; the next trading day's open stands
in for `confirm_entry()`'s live intraday quote (the earliest, most
conservative substitute available from daily OHLC alone).

**Not modeled**: stocks have no stateful radar-state machine the way
crypto's `CryptoRadarStateTracker` provides (confirmed - `app/radar/
state.py` is never imported anywhere under `app/stock_radar/`), so unlike
the crypto harness's `STATE_EXIT`, an open stock backtest position only
ever closes on STOP, TARGET, or END_OF_DATA - this answers "is the entry
signal good", not "how well would P16/P17's trailing-stop management have
performed", the same scope boundary the crypto harness already draws.

Runnable via `scripts/backtest_stocks.py` (`BACKTEST_SYMBOLS`,
`BACKTEST_HISTORY_DAYS` env vars) - real KIS HTTP calls, nothing written
to the database, prints a report only, same shape as
`scripts/backtest_crypto.py`.

**What this does NOT yet prove**: the harness's `too_late_excluded_count`/
`rejected_reconfirm_count`/`no_buy_or_watch_count` are real counts of how
often each gate fired during a replay - not yet a counterfactual "and
skipping it was the right call" (that needs simulating the trade that
*would* have happened had the gate not fired, then comparing outcomes -
a genuine Bad-Trade/Chase-Avoidance-*Rate*, not just an activity count).
Wiring this harness's real trade outcomes into `/api/dashboard/
performance`'s `risk_avoidance` field (replacing its current
7-day-activity-count stand-in) is the natural next step, once the harness
itself has been run against enough real history to trust its numbers.

## P41 - Intraday RS/Heat Read API

Closes the "dedicated read helper/API for intraday RS - still a
follow-up, not yet built" line from this doc's own Known gaps (below).
`app/stock_radar/regime_persistence.py`'s `get_intraday_interaction_readings()`/
`get_intraday_heat_readings()` read the real per-run history already
accumulating in `regime_relative_strength`/`overheat_scores` (P34/P35) -
`scripts/reconfirm_entries.py` computes `observed_at = datetime.now(UTC)`
once per run and persists it unchanged into both tables, so every real
`reconfirm_entries.py` run (the P32 scheduler triggers one roughly every
`SCHEDULER_STOCK_INTERVAL_SECONDS` during KRX hours) leaves a distinct,
queryable timestamp behind - not just the latest reading.

Exposed via `GET /api/stock-radar/{symbol}/intraday` (optional `since`
query param, ISO 8601 - defaults to the start of today's KST calendar
day). Returns two chronological lists (`interaction_readings`/
`heat_readings`) rather than trying to merge them into one combined
timeline, since interaction rows depend on an extra
`get_investor_trend()` call per CONFIRMED symbol that can fail
independently of the heat computation for the same symbol/run (see
P34's own module docstring) - the two are not guaranteed 1:1 even when
persisted moments apart in the same run.

No frontend view yet - this pass is the backend read path only, proven
by real DB-backed tests
(`test_regime_persistence.py`/`test_stock_radar_intraday_api.py`); a
시장/종목 tab UI to actually display the timeline is a natural, separate
follow-up.

## P42 - Frontend/UX pass (pending-approval visibility, live P&L, auto-refresh)

Closes a set of frontend gaps found by reviewing the six-tab app end to
end: the home screen's "지금 확인" button did nothing, no page refreshed
itself once mounted, open positions showed entry/stop but never a live
price or P&L, the stock radar list had no freshness or KOSPI/KOSDAQ
filter, and a failed fetch left a dead end with no way to retry short of
reloading the whole app.

- **Pending-approval visibility**: `GET /api/approvals` (backend) is a
  read-only listing of the authenticated user's pending (non-terminal,
  non-expired) approvals, joined with the recommendation each is for.
  "지금 확인" now calls it and renders the list inline. It deliberately
  changes nothing about *deciding* an approval - `Approval.token_hash`
  only ever stores a hash, the plaintext token only ever existed at
  creation time (sent via Kakao), and this endpoint never exposes one.
  The real Kakao-delivered token stays the only way to open/decide an
  approval (see `app/api/approvals.py`'s module docstring); weakening
  that for in-app convenience was explicitly rejected.
- **Live position P&L**: `GET /api/dashboard/positions/live-prices`
  fetches one real quote per open position (KIS for STOCK, Upbit for
  CRYPTO) and computes unrealized P&L, degrading individual fields to
  `null` - never a stale or fabricated number - on any fetch failure.
  Kept as its own endpoint rather than folded into `/summary`, since it
  makes real external calls per request; the frontend polls it on its
  own, slower cadence (20s) than the position list itself (30s), and only
  while the 포지션 tab is mounted.
- **Auto-refresh + retry**: a shared `usePolledFetch` hook
  (`frontend/src/hooks/usePolledFetch.ts`) now backs every one of the six
  tabs - each polls its own data on a cadence matched to how often that
  data actually changes (30s for summary-backed tabs and the stock radar
  scan's own poll, 60s for market/performance), keeps the last good data
  on screen through a failed background refresh, and exposes a "다시
  시도" retry button whenever a fetch does fail.
- **Stock radar freshness + market filter**: `/api/stock-radar/latest`
  candidates now carry the security's `market` (KOSPI/KOSDAQ), and the
  종목레이더 tab shows how long ago the underlying scan ran (relative to
  `scored_at`) plus a KOSPI/전체/KOSDAQ filter chip row - so a stale scan
  or an irrelevant market's candidates are never silently mixed in with
  current ones.

All five verified with real backend tests (`test_approvals_api.py`,
`test_dashboard_api.py`) and by loading each changed page in a browser
against a mocked API (login prompt, pending-approval list, live-P&L
color/sign, freshness text, and the market filter all screenshotted and
confirmed working) - no new frontend component tests were added beyond
updating existing fixtures for the new `market` field, since none of
these five pages had a pre-existing coverage gap this pass needed to fix
beyond what the manual/backend verification already covers.

## P44 - Exclude ETF/ETN from the PRE-BREAKOUT scan universe

A real deployment run of the P39 full-universe rotation surfaced the
종목레이더 tab filled with ETF/ETN codes (names ending "...ETN",
"...ETN(H)") ranked alongside real company stocks, several scoring
higher than genuine stock candidates - reported directly by the user from
a live screenshot. Root cause: `app/db/models.py`'s `SecurityRow.is_etf`/
`is_etn` columns have existed since P23 but were never populated by
anything, and `app/integrations/kis/krx_master.py`'s KOSPI/KOSDAQ master-
file parser never read the master file's own `ETP` flag (KIS's own way of
marking "this is an ETF/ETN, not a plain stock") - so nothing ever
excluded them from the P39 rotation, and the PRE-BREAKOUT score's
institutional-accumulation/OBV/earnings-driven signals got computed for
index-tracking derivative products they were never designed to evaluate.

Fixed by adding the real `ETP` flag to `MasterRow`/`_parse_master_text()`
(byte offset independently re-derived from KIS's public reference scripts
and cross-checked against this module's pre-existing halted/
administrative/volume offsets, which matched exactly - see that module's
own docstring for the full provenance) and excluding `is_etp` rows in
`rank_tradable_by_liquidity()`, the same place halted/administrative
symbols were already excluded. Deliberately does **not** attempt to split
ETF from ETN specifically (`SecurityRow.is_etf`/`is_etn` stay unpopulated,
same as before) - the reference master file has one shared `ETP` flag for
both, and the 2-character group code that would distinguish them was not
independently confirmed, so this project doesn't guess at that split. One
combined `is_etp` exclusion cleanly fixes the reported symptom without
fabricating a finer distinction it can't back up.

Takes effect on the next real scan run once redeployed - see
`docker compose up -d --build backend scheduler` in this project's own
deployment notes.

## Known gaps - explicitly out of scope this pass, not silently skipped

Some pieces the original request asked for still have no real data
source, or need infrastructure well beyond what a single pass can
honestly build and test. Listed here rather than faked:

- **Leader-Laggard Engine** (분석 선두주 대비 후발 공급망 종목 찾기): needs
  a supply-chain/sector-peer mapping data source (same customer, same
  process, same supply chain) this project has never had access to.
  Checked directly (`grep sector_code app/integrations/kis/krx_master.py`
  returns nothing) - `SecurityRow.sector_code`/`sector_name` are declared
  in the schema but never populated by the KRX master parser. Fabricating
  peer relationships would be worse than not having the feature.
- **RS_5m/RS_15m/RS_30m/RS_60m intraday persistence**: the stock radar
  (P23 onward) is built entirely on *daily* candles - there is no
  intraday tick/minute-bar store for stocks the way the crypto radar has
  for Upbit. Partial, real substitute already in place: P34/P35's
  `regime_relative_strength`/`overheat_scores` tables are append-only and
  get a new row every `reconfirm_entries.py` run - i.e. every ~30 minutes
  during KRX hours under the P32 scheduler - so multiple real intraday
  snapshots per symbol per day already exist and are queryable by
  `observed_at`. Coarser than tick-level RS, but real data, not a guess.
  The read API is now built (P41, above); a frontend view of it is still
  a follow-up.
- **Weekly weight auto-retuning / labeling learning loop**: `regime_
  relative_strength.label` and a symbol's eventual outcome give the raw
  material for this, but the retuning process itself needs real trading
  history accumulated over real weeks - there's nothing to learn from on
  day one, and building the mechanism without real data to validate it
  against would be guessing at a shape, not implementing a working loop.
- **Bad Trade Avoidance Rate / Chase Avoidance Rate / No-Trade Accuracy
  KPIs**: these require actual historical trade outcomes tracked over
  time. The stock radar now has a backtest harness (P40, above) - the
  piece that was genuinely missing before - but the harness itself only
  reports gate-activity counts (how often TOO_LATE/reconfirm-reject/
  WATCH-NO_BUY fired), not yet the counterfactual "and that was the right
  call" comparison a real *rate* KPI needs. `/api/dashboard/performance`'s
  `risk_avoidance` field still reports the older, simpler real-count
  stand-in (TOO_LATE exclusions + NO_TRADE_DAY days over the last 7 days
  from live scans, not backtest replay) - wiring the two together is the
  next step, not yet done.
