# Multi-Asset Pre-Breakout Radar v6.0 — 11-Day Autonomous Development Master Spec

> Source of truth for phases P0–P22. Copied verbatim from the project owner's
> spec so every future development day can refer back to it without relying on
> conversation history. Day mapping: Day 0 = P0 (bootstrap), Day N = P(2N-1) + P(2N)
> for N = 1..11, ending Day 11 with P21 + P22.

## PROJECT GOAL

11일 동안 P0부터 P22까지 순차적으로 개발하여:

1. KOSPI/KOSDAQ 실시간 Radar
2. KIS 실시간 데이터
3. Toss 주문 연동
4. Upbit 24/7 Crypto Sentinel
5. Human Approval Trading
6. Partial Profit Taking
7. Position Guardian
8. Kakao Approval Notification
9. Mobile-first UX/UI
10. Self-Healing Runtime
11. Paper Trading
12. Live-Safe Readiness

까지 구현한다.

이 일정은 IMPLEMENTATION TARGET이다. 외부 API 승인, 계정권한, 네트워크, 서비스
장애, 카카오/증권사/거래소의 정책에 의해 일정이 지연될 수 있다. 절대로 테스트하지
않은 기능을 COMPLETE라고 표시하지 않는다.

## A. Absolute safety rule

- `LIVE_TRADING = FALSE` by default.
- Default trading mode: `PAPER_APPROVAL`. Live entry requires `LIVE_APPROVAL`.
- `LIVE_AUTO` is always `DISABLED`. AI must never create a new live position
  without explicit user approval. Position protection on already-approved
  positions runs automatically.

## B. Human-in-the-loop flow

```
MARKET SCAN -> OPPORTUNITY DETECTION -> RANKING -> RECOMMENDATION -> RISK REVIEW
  -> KAKAO ALERT -> USER OPENS APPROVAL PAGE -> AUTHENTICATION -> USER APPROVAL
  -> PRE-ORDER REVALIDATION -> ORDER -> FILL -> POSITION GUARDIAN
  -> PARTIAL PROFIT -> RUNNER MANAGEMENT
```

Ranking ≠ Recommendation. Recommendation ≠ Approval. Approval ≠ Guaranteed
Order. The Risk Engine can reject even after user approval.

## C. Kakao approval architecture

Kakao Login + Kakao Talk "Send to Me" + secure approval web link. The Kakao
message button must never call a trade-execution endpoint directly — it links
to `https://APP_DOMAIN/approve/{one_time_token}`, which requires the
authenticated Kakao user plus an app PIN or passkey/WebAuthn re-check before
approval is accepted.

## D. Approval token security

Single-use, short TTL (120–300s), server-stored hash, bound to
`recommendation_id` and `user_id`. Consumed on use; reuse returns HTTP 410.

## E. Approval states

`CREATED, NOTIFIED, OPENED, APPROVED, REJECTED, EXPIRED, INVALIDATED, EXECUTED,
BLOCKED_BY_RISK` — recorded in an `approval_events` table.

## F. Pre-order revalidation

After approval, re-check: current price, entry deviation, signal score/state,
VWAP, RVOL, turnover, spread, slippage, liquidity, BTC/stock regime, market
data health, execution API health, portfolio exposure, daily loss, position
duplication. A failure yields `TRADE_INVALIDATED` even though the approval was
received, surfaced to the user as "승인은 완료됐지만 시장 조건이 변경되어
주문하지 않았습니다."

## G–J. Partial profit and runner management

Default split: T1 sells 30%, T2 sells 30%, runner keeps 40% (configurable).
After T1 fill, stop may move to breakeven or a structural protection level but
never below the previously allowed loss. After T2, remaining runner position
uses dynamic trailing (ATR, realized volatility, VWAP, EMA, recent swing low,
orderflow, distribution risk, high giveback) that only tightens, never loosens.

## K. Project priority order

1. Position Protection
2. Account Integrity
3. Order Integrity
4. Risk
5. Market Data Integrity
6. Availability
7. Signal Quality
8. UX
9. Performance

## L–R. Self-healing principle

Flow: `DETECT -> CLASSIFY -> SAFE STATE -> DIAGNOSE -> RECOVER -> VERIFY ->
RESUME OR REMAIN PAUSED`.

**Auto-recoverable:** WebSocket disconnect, transient Redis failure, DB
connection reset, API timeout, temporary DNS failure, process crash, stale
cache, expired access token (with an official refresh mechanism), consumer
lag, frontend API retry, temporary notification failure.

**Never auto-resolved (blocks new trades, raises a P1 alert, requires manual
review):** unknown order status, position mismatch, unexpected broker
holdings, unknown fill quantity, duplicate order ambiguity, account
authorization error, manual order conflict, unexpected asset balance.

**Never done by the self-healing engine:** create arbitrary orders, buy to
recover a loss, liquidate positions arbitrarily, widen a stop-loss, guess an
API schema, change credentials.

Implementation lives under `backend/app/supervisor/`: `health_monitor.py`,
`failure_classifier.py`, `recovery_manager.py`, `service_restart.py`,
`reconciliation.py`, `incident_manager.py`, `self_test.py`. Health states:
`HEALTHY, DEGRADED, RECOVERING, PAUSED, CRITICAL, OFFLINE`. Every incident
records: id, service, severity, failure_type, detected_at, safe_action,
recovery_attempts, recovered_at, verification_result, human_action_required.

## S–U. Autonomous development rules

Each phase: `AUDIT -> IMPLEMENT -> FORMAT -> LINT -> TYPECHECK -> UNIT TEST ->
INTEGRATION TEST -> FAILURE TEST -> AUTO FIX -> RETEST -> SECURITY CHECK ->
DOCUMENT -> COMMIT`. A failing test blocks moving to the next phase.

Auto-fix loop: up to 5 attempts (classify failure -> inspect logs -> root
cause -> minimal fix -> rerun affected tests -> rerun full phase tests). After
5 failed attempts: `PHASE BLOCKED`, reported with root cause, files, stack
traces, attempts, and the manual action needed.

Never: swallow exceptions to hide failures, delete or weaken tests to force a
pass, lower a threshold to force a pass, replace a real integration with a
mock in an integration test, fake an API response, hardcode success.

## V–Y. Daily development automation

`scripts/dev_day_runner.py --day N` runs: git status check -> backup branch ->
current phase check -> environment health check -> phase A implement/test/
auto-fix/gate/commit -> phase B implement/test/auto-fix/gate/commit -> daily
report. State lives in `.devstate/state.json` (never hand-edited outside the
runner). Daily reports live in `docs/daily/DAYNN.md` and record: completed
phase, files created/modified, tests run/passed/failed, fixes applied,
security findings, API status, known problems, screenshots, UX findings, next
day. Actual daily execution is driven by an external scheduler (OS task
scheduler / systemd timer / cron), not by an open Claude Code chat session;
live trading credentials never go into a CI runner.

## Z. 11-day roadmap

| Day | Phases |
|-----|--------|
| 0   | P0 Bootstrap |
| 1   | P1 + P2 |
| 2   | P3 + P4 |
| 3   | P5 + P6 |
| 4   | P7 + P8 |
| 5   | P9 + P10 |
| 6   | P11 + P12 |
| 7   | P13 + P14 |
| 8   | P15 + P16 |
| 9   | P17 + P18 |
| 10  | P19 + P20 |
| 11  | P21 + P22 |

## Phase summaries

- **P0 Bootstrap** — repo skeleton (`backend/ frontend/ tests/ docs/ scripts/
  docker/`), Python 3.12 FastAPI, React/Vite/TS, PostgreSQL/TimescaleDB, Redis,
  Docker Compose, `GET /health/live` and `GET /health/ready`.
- **P1 Common domain model** — Pydantic models (AssetType, Exchange, Market,
  Quote, Trade, OrderBook, Candle, Signal, Recommendation, Approval,
  TradePlan, Order, Fill, Position, RiskState, SystemHealth) mirrored as
  TypeScript types on the frontend.
- **P2 Database + event bus** — Timescale tables for ticks/candles/features/
  signals/recommendations/approvals/trade_plans/orders/fills/positions/
  protective_orders/system_health/incidents/audit_logs/performance; Redis
  Streams for market/feature/radar/recommendation/approval/order/position/
  health events.
- **P3 KIS realtime** — official KIS REST + WebSocket auth/tick/orderbook with
  reconnect and subscription restore; mocks allowed only in unit tests.
- **P4 Stock feature + radar** — VWAP, RVOL, turnover acceleration, opening
  range, price action, relative strength, liquidity, market regime; TOP200 /
  TOP30 / TOP5 state machine.
- **P5 Toss account** — OAuth, accounts, holdings, buying power, order
  queries; no order placement yet.
- **P6 Stock recommendation engine** — entry zone, structural stop, T1/T2,
  runner %, position size, expected risk, R:R, reasons, risks, TTL; no live
  order; frontend recommendation card.
- **P7 Upbit public WS** — ticker/trade/orderbook/candle with 24/7 reconnect,
  heartbeat, REST secondary price verification.
- **P8 Crypto feature engine** — VWAP, RVOL, turnover, volatility, spread,
  orderbook imbalance, BTC relative strength, liquidity, slippage, BTC regime,
  pump risk.
- **P9 Crypto radar** — Upbit KRW universe TOP200/TOP30/TOP5 with hysteresis
  and states `STEALTH, ACCUMULATION, PRE_BREAKOUT, BREAKOUT,
  CONFIRMED_BREAKOUT, PULLBACK, RE_ENTRY, DISTRIBUTION, FAILED_BREAKOUT,
  PUMP_RISK, AVOID`.
- **P10 Technical ensemble** — Bollinger, Keltner, MACD, RSI, MFI, ATR, PSAR,
  VWAP strategy, breakout strategy, backtested; scores never order directly.
- **P11 Smart money + psychology** — observable signals only (absorption,
  support defense, low-volume pullback, buy aggression, volume compression;
  FOMO, chasing, anchoring, round numbers, crowd exhaustion). No unsupported
  manipulation claims.
- **P12 Kakao login + notification** — Kakao OAuth/Login, token storage,
  refresh, `talk_message` consent, send-to-me notification with approval
  link; official APIs only, no faked success.
- **P13 Secure approval UX** — mobile approval page (symbol, price, entry,
  stop, T1/T2, runner, risk, score, confidence, reasons, risks, countdown;
  buttons: 승인 / 금액변경 후 승인 / 보류 / 거절) gated by authenticated user +
  one-time token + optional PIN/passkey.
- **P14 Pre-order revalidation** — re-score market, TTL, entry drift, spread,
  slippage, liquidity, regime, risk, broker health -> `VALID / INVALIDATED /
  EXPIRED`.
- **P15 Execution providers** — Toss (place/cancel/modify) and Upbit
  (place/cancel/status), idempotent, timeout reconciliation, no blind
  retries.
- **P16 Position Guardian** — independent service managing fills, stop, T1,
  T2, runner, trailing, failed-breakout exit, position sync; a Guardian crash
  turns new buys off.
- **P17 Partial profit engine** — TradePlan with initial_qty/t1_percent/
  t2_percent/runner_percent (default 30/30/40), state derived from actual
  fills, never assumed requested fill.
- **P18 Risk + kill switch** — risk per trade, max exposure, max positions,
  daily risk, consecutive stop, market crash, pump risk, liquidity risk,
  position mismatch, unknown order, Guardian unhealthy -> stop new trades
  while existing protection remains.
- **P19 Self-healing + watchdog** — health monitoring, failure classification,
  service restart, WS/DB/Redis reconnect, token refresh, cache repair;
  critical unknown states pause the system; incident dashboard.
- **P20 Paper trading + replay** — real market feed with simulated fees, tax,
  spread, slippage, partial fill, latency; historical replay with no lookahead
  bias.
- **P21 UX/UI finalization** — mobile-first at 375/390/412px widths; nav:
  Radar / 추천 / 포지션 / 시장 / 성과 / 시스템; home shows market regime, BTC
  regime, system health, pending approvals, top opportunities, positions,
  risk used; one-hand usability, 44px minimum touch targets, never
  color-only signaling.
- **P22 Soak / release readiness** — full test sweep (unit, integration,
  security, reconnect, recovery, order state, position state, partial fill,
  kill switch, Kakao approval, mobile, restart), 24h minimum / 72h target soak,
  `docs/RELEASE_READINESS.md` output with final state `MONITOR READY / PAPER
  READY / LIVE_APPROVAL READY / BLOCKED`. `LIVE_AUTO` stays disabled
  regardless of outcome.

## UX principles

The user does not need to understand the quant system. The home screen must
answer, within 5 seconds: is the market safe right now? is there a
recommendation? does something need approval? are open positions safe? how
much of today's risk budget is left?

## Security

No plaintext secrets, no secrets in frontend code, no approval secrets in URL
logs, CSRF protection, secure cookies, SameSite, TLS in production, rate
limiting, approval replay prevention, secret scanning, dependency scanning.

## Environment separation (DEV / STAGING / PRODUCTION)

```
DEV        Claude Code development, mock + test credentials, no live trading permission
             |  verify
STAGING    real WebSocket feeds, paper trading, test/demo account
             |  approve
PRODUCTION live data, LIVE_APPROVAL, no Claude Code write access to prod code
```

Claude Code's autonomous fix loop applies through DEV/STAGING only. In
production, a failure goes through Watchdog -> safe stop -> service restart
-> state recovery -> reconciliation; code fixes are made on DEV, tested, and
deployed — never patched live by an AI in production.

## Final Claude Code instruction (paraphrased, always in force)

Start from P0; do not attempt every phase at once. Audit the existing
repository first and preserve working functionality. Implement only the
active phase, run tests, and if they fail diagnose and repair (up to 5
repair cycles) — never modify tests merely to force a pass, never fake a
third-party API response as real. Never enable live trading and never place a
real order without explicit user approval in `LIVE_APPROVAL` mode. Always
protect an already-approved position even while the user is offline. Kakao
notification is a notification channel, not a direct unauthenticated order
interface. If market, account, order, Guardian health, or position state is
uncertain, block new trades. If a recommendation expires, do not trade. After
T1, take partial profit and protect the remainder; after T2, retain the
configured runner quantity under risk-tightening trailing logic. Do not
average down by default. Write a detailed daily report after each run, and
stop once the current day's phase gates pass — wait for the next scheduled
run rather than continuing further.
