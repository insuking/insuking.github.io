# Release Readiness — Multi-Asset Pre-Breakout Radar v6.0

**Assessed:** 2026-09-07, end of Day 11 (P22), the final day of the 11-day
plan (docs/MASTER_SPEC.md).

## Final state: MONITOR READY

`LIVE_AUTO` stays `DISABLED` regardless of this outcome, per
docs/MASTER_SPEC.md section A — nothing in this assessment changes that,
and nothing should.

This is not `PAPER READY` or `LIVE_APPROVAL READY` yet, and it is not
`BLOCKED` either — every test that *can* run in this environment passes,
and the safety-critical subsystems (kill switch, Position Guardian,
self-healing/watchdog, risk engine) are proven against real local
infrastructure. What is missing to advance is listed explicitly below,
and none of it is a defect found in what was built — it is work that
genuinely cannot be done from this sandbox (real broker/exchange
credentials, a real multi-day soak, a live market feed).

## What was actually verified this run

- **Backend:** `ruff check .` clean, `mypy app tests/backend` clean (170
  source files), full pytest suite **521 passed, 9 skipped** (skips are
  all `BLOCKED` real-credential/real-egress cases, listed below — never a
  faked pass). Run twice back to back for stability; both runs identical.
- **Frontend:** `oxlint` clean (2 pre-existing style warnings, no errors),
  `tsc -b && vite build` clean, `vitest run` **26 passed** across 6 test
  files.
- **Browser smoke test** (Playwright, real Chromium, not simulated): the
  P21 nav shell renders all six tabs (Radar/추천/포지션/시장/성과/시스템)
  at all three P21-required widths (375/390/412px), every touch target
  measured **exactly 44px** minimum height, no horizontal overflow at any
  width, zero console errors, and every tab's route/heading matched.
- **Soak-lite** (`backend/scripts/soak_lite.py` — see its module docstring
  for exactly what this is and is not): 30 cycles then 100 cycles of
  DB/Redis health-check + reconnect + a full P19 self-healing recovery
  cycle + a full P20 paper buy/sell cycle, against real local
  Postgres/Redis. **0 errors across 130 total cycles.** Cycle latency
  stayed flat (mean ~0.078s, no upward drift) and process RSS growth
  decelerated sharply after the first ~30 cycles (+13MB → only +6MB more
  over the next 70), consistent with one-time connection-pool/cache
  warmup rather than a per-cycle leak. See docs/daily/SOAK_LITE.md for the
  raw numbers from the last run.

## Test sweep vs. docs/MASTER_SPEC.md P22's categories

| Category | Covered by | Status |
|---|---|---|
| Unit | Every phase's pure-function tests (indicators, strategies, cost model, fill simulator, kill-switch evaluation, accounting, regime classifier, etc.) | PASS |
| Integration (own infra) | DB-backed tests across all phases against real local Postgres/Redis (Guardian, Risk, Approval, Supervisor, Paper Trading, Dashboard) | PASS |
| Integration (external APIs) | `test_kis_integration.py`, `test_toss_integration.py`, `test_toss_execution_integration.py`, `test_upbit_integration.py`, `test_upbit_execution_integration.py`, `test_kakao_integration.py` | **BLOCKED** — no real credentials/egress in this sandbox (see below) |
| Security | Rate limiting (`test_approval_rate_limit.py`), single-use/short-TTL approval tokens (`test_approval_tokens.py`), PIN re-check (`test_approval_pin.py`), OAuth state CSRF (`test_auth_api.py`), no-plaintext-secret config pattern throughout | PASS (see gaps below) |
| Reconnect | `test_kis_ws_client.py`, `test_upbit_ws_client.py` (subscription restore), `test_supervisor_service_restart.py`, `soak_lite.py`'s repeated DB/Redis reconnect cycles | PASS |
| Recovery | `test_supervisor_recovery_manager.py`, `test_supervisor_health_monitor.py`, `test_supervisor_reconciliation.py`, `test_supervisor_incident_manager.py` | PASS |
| Order state | `test_toss_execution.py`, `test_upbit_execution.py`, `test_paper_trading_ledger.py` (`UNKNOWN`/idempotency/reconciliation paths) | PASS |
| Position state | `test_partial_profit_accounting.py`, `test_partial_profit_service.py`, `test_guardian_position_sync.py` | PASS |
| Partial fill | `test_partial_profit_accounting.py`'s threshold-based state derivation, `test_paper_trading_fill_simulator.py`'s participation-cap partial fills | PASS |
| Kill switch | `test_risk_kill_switch.py`, `test_risk_service.py` | PASS |
| Kakao approval | `test_kakao_auth.py`, `test_kakao_token_store.py`, `test_kakao_notify.py`, `test_approvals_api.py`, `test_auth_api.py` (mocked-HTTP unit tests); `test_kakao_integration.py` **BLOCKED** | PASS (unit) / BLOCKED (real) |
| Mobile | P21 nav/layout browser smoke test above (375/390/412px, 44px targets, no color-only signaling) | PASS |
| Restart | `test_db_reconnect.py`, `test_supervisor_service_restart.py`, `soak_lite.py` | PASS |

## Known gaps (why not PAPER READY yet)

1. **No real broker/exchange credentials were ever available in this
   development sandbox.** Every KIS, Toss, Upbit-authenticated, and Kakao
   real-connection test is `BLOCKED`, not faked passing — this has been
   true and honestly reported since P3 (Day 2). The HTTP client code
   against each provider's documented API contract is unit-tested with
   mocked transports, and where a real bug was found this way (e.g. P15's
   `X-Tossinvest-Account` header fix) it was fixed — but none of it has
   been exercised against the real KIS/Toss/Upbit/Kakao servers.
2. **No live market data pipeline is wired end-to-end.** P3/P7 built
   real WebSocket clients; nothing in this 11-day scope adds a
   continuously-running scheduler that keeps them connected and writing
   `candles`/`market_ticks` around the clock — the dashboard's
   `market_regime`/`btc_regime` (P21) honestly report `null` on a fresh
   database rather than fabricate a reading, and did exactly that in this
   assessment's own database.
3. **The real 24h-minimum / 72h-target soak (docs/MASTER_SPEC.md P22) was
   not run.** What was run — 130 bounded cycles, a few minutes total — is
   a real, honest signal against gross leaks/crashes under repetition, not
   a substitute for observing a live deployment over real wall-clock days.
   See `backend/scripts/soak_lite.py`'s module docstring.
4. **`kakao_redirect_uri`/Kakao app credentials are unconfigured**, so
   `POST /api/auth/kakao/callback` (P21) has only ever run against a
   mocked `KakaoAuth` in tests — the state-CSRF handling, `KakaoTokenStore`
   persistence, and error mapping are proven; the real Kakao consent
   screen round trip is not.
5. **`market_index_symbol` is unset by default** (see `app/core/config.py`)
   — there is no established convention yet for which KIS index code
   represents "the KOSPI/KOSDAQ benchmark", so `market_regime` stays
   honestly `null` rather than guessing one. This needs a real decision,
   not a code fix.

## Security checklist (docs/MASTER_SPEC.md, Security section)

| Item | Status |
|---|---|
| No plaintext secrets | PASS — every credential field defaults to `""`/"not configured", PIN stored as PBKDF2 hash only |
| No secrets in frontend code | PASS — frontend never holds a broker/Kakao secret; `X-User-Id` is an opaque id, not a credential |
| No approval secrets in URL/logs | PASS — approval tokens are single-use, hashed at rest (`app/approval/tokens.py`) |
| CSRF protection | PASS for the OAuth login flow (state nonce, single-use, Redis TTL, P21); the approval decide endpoint has no CSRF token because it is not cookie-authenticated (`X-User-Id` header, not a cookie — see `app/api/approvals.py`'s docstring) |
| Secure cookies / SameSite | N/A — this design deliberately has no session cookie (see `app/api/approvals.py`) |
| TLS in production | Not this repo's concern (deployment-layer) — not assessed |
| Rate limiting | PASS — `app/approval/rate_limit.py`, applied to the PIN-guessing surface (P21) |
| Approval replay prevention | PASS — single-use token, hash lookup, HTTP 410 on reuse (P13) |
| Secret scanning | Not run in this session — no secret-scanning tool was wired into the gate; every credential in the repo's own config is empty-by-default and `.env`-sourced, but this is a manual audit, not a tool-verified guarantee |
| Dependency scanning | Not run in this session — same caveat |

## Path from MONITOR READY to PAPER READY

1. Provision real KIS/Upbit read credentials in a STAGING environment
   (docs/MASTER_SPEC.md's DEV/STAGING/PRODUCTION separation) and confirm
   the real-connection integration tests currently `BLOCKED` actually pass.
2. Wire a continuously-running market-data loop (not built in P0-P22)
   that keeps P3/P7's WebSocket clients connected and persists
   candles/ticks, so `market_regime`/`btc_regime` stop reporting `null`.
3. Decide and configure `market_index_symbol`.
4. Run the real 24h-minimum soak against that STAGING deployment, watching
   the P21 시스템 tab and P19 incident log for anything the bounded
   soak-lite run couldn't surface (real network flakiness, real overnight
   load patterns, a real multi-day connection).
5. Only after all of the above: re-run this checklist. `LIVE_APPROVAL
   READY` additionally requires real Toss/Upbit trading credentials
   verified end-to-end and a human explicitly deciding to enable
   `LIVE_TRADING` — `LIVE_AUTO` stays disabled regardless, permanently, per
   docs/MASTER_SPEC.md section A.
