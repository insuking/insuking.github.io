# SmartCoin UI Redesign (P45-P46)

The user shared five real UI mockups (branded "SmartCoin") for a dark-theme
redesign: a "시작 안전점검" onboarding safety checklist, a home dashboard
with a total-assets card and trend chart, a market-radar candidate list,
a recommendation detail view, and an approval decision modal. This phase
applied the visual system and built the three genuinely new capabilities
the mockups needed that didn't exist yet - all backed by real data, per
this project's standing rule against fabricated/sample data.

## What changed

### Dark theme

`frontend/src/index.css`'s design tokens were rewritten from the original
Toss-style light theme to a single fixed dark navy theme (no light/dark
toggle - the mockups show one consistent look). Because the whole
frontend is already built on CSS custom properties (`--color-*`), this
cascaded to every existing page automatically - `App.css`'s `.card`/
`.cta`/`.stat-*`/etc. classes needed only a handful of direct edits
(`.card` gained a border for definition on a dark background;
`.status-warn`/`.filter-chip--active` swapped a hardcoded light-theme
color for a token).

**Gain/loss convention flip**: the original light theme deliberately used
the Korean-market convention (RED = up/gain, BLUE = down/loss, matching
Toss). The mockups use the international/crypto-exchange convention
(GREEN = up/gain, RED = down/loss) - `--color-gain`/`--color-loss` were
swapped accordingly, a deliberate reversal per the user's own reference
design, not an oversight.

### New capability: real combined account balance

Neither KIS nor Upbit account-balance reads existed in this project
before this pass - see `backend/app/account/balance.py`'s own docstring
for the field-provenance details (KIS's 주식잔고조회 tr_id
`TTTC8434R`/`VTTC8434R`, Upbit's `GET /v1/accounts`). New endpoints:
`GET /api/dashboard/balance` (live) and `/balance/history?window=1d|1w|1m|all`
(real periodic snapshots via a new `account_balance_snapshots` table,
written every scheduler cycle by `scripts/snapshot_balance.py`). The home
screen's "총자산" stat card and "자산 추이" sparkline read these - an
empty/flat chart on a fresh deployment is the honest state until the
scheduler has run a few times, never a fabricated curve.

### New capability: "시작 안전점검" onboarding gate

`frontend/src/pages/SafetyCheckPage.tsx`, gated by a `localStorage` flag
(`safetyCheckPassed`, shown once per browser) in `App.tsx` - the
`/approve/:token` deep link and the Kakao OAuth callback route both
bypass it entirely. Reads `GET /api/dashboard/safety-check` - 5 items,
every one a real, verifiable signal, never a hardcoded green row:

1. **Demo/실거래 모드** - `Settings.live_trading`.
2. **거래소 연결 정상** - a real lightweight call per configured broker
   (KIS `get_quote`, Upbit `get_ticker_price`).
3. **출금 권한 비활성** - reframed from an unverifiable question (neither
   broker's public API exposes a way to introspect an API key's granted
   permissions) to the actually-verifiable and more relevant claim: this
   app's own integration code never calls any withdrawal endpoint for
   either broker.
4. **오늘 최대손실 한도** - whether the latest real `RiskStateRow` has a
   configured limit.
5. **긴급정지 점검 완료** - whether the risk-state storage is reachable.

"실거래 모드로 전환" is intentionally a disabled, informational button,
not a working toggle - `LIVE_TRADING` stays a server-side deployment
setting (`.env`/`docker-compose.yml`), never something a UI button can
flip, so accidentally enabling real trading always takes a deliberate
infrastructure change.

**P46 fix: "안전하게 시작하기" only requires items 1 and 5 to be `ok`**,
not all five. It originally required `all_ok` (every item), which meant
a fresh/local deployment with no KIS/Upbit keys configured yet, or one
without outbound internet reach to Upbit - the common case on a first
`docker compose up` - would show a permanent "확인 필요" on item 2
(거래소 연결 정상) and sometimes item 4 (no risk state recorded until the
scheduler's first cycle), and the start button would never enable at
all. Those two are real operational status, not danger signals, and this
screen has no effect on `LIVE_TRADING` either way - so they still render
their real status honestly, they just don't block entry. Items 1 (don't
silently run live without seeing the LIVE banner) and 5 (the risk-state
storage every safety mechanism in this project depends on must actually
be reachable) are what genuinely mean something is unsafe, so those are
what gate the button.

### New capability: manual emergency stop

The home screen's red "긴급정지" button calls `POST
/api/dashboard/emergency-stop` (and `/clear` to reverse it) - both
Kakao-session-gated the same way `/api/approvals`' endpoints are. Rather
than building a parallel kill-switch mechanism, this inserts a new
`RiskStateRow` with `kill_switch_active` forced on/off (numeric fields
carried forward from the latest real state) - `RiskService.
should_block_new_trades()` (P18) already reads "latest row by `as_of`"
as current, so the effect is immediate with zero new blocking logic.

## P46: position management + a richer emergency-stop screen

The user shared four more mockups (06 주문 최종확인, 07 포지션 관리, 08
분할청산 진행, 10 비상정지와 복구). This phase built a position detail
page and a dedicated emergency-stop/recovery page, each backed by real
data, plus a reusable press-and-hold confirmation control for the
destructive real-money action this batch introduces.

### New capability: manual position close ("즉시 청산")

Before this pass, **nothing in this project could place a real SELL
order against an existing position** - Guardian's own automatic exits
(`app/guardian/service.py`) are decision-only by design (see its own
module docstring: turning a decision into a real order was left to "a
scheduled job, which doesn't exist anywhere in this repository yet").
`app/positions/manual_close.py`'s `close_position_market()` is the first
thing that does: one real market SELL for a position's full remaining
quantity, via the same `ExecutionProvider.place_order()` every BUY order
already goes through (`_require_live_trading()` gate included, unchanged
- `LIVE_TRADING` stays a server-only setting). `POST
/api/positions/{id}/close` wires it to KIS or Upbit by `asset_type`, the
same routing `app/api/approvals.py` already uses for BUY orders, and
requires the same Kakao-session authentication as every other real
action in this project.

### New capability: position detail + Guardian pause

`GET /api/positions/{id}` (real live quote + real protective-order
target prices) and `POST /api/positions/{id}/guardian` (toggles the one
real flag `app/guardian/service.py:93` already checks before doing
anything for that position - a paused position genuinely stops receiving
trailing-stop tightening and failed-breakout exits, not a label change).

**T1/T2 progress is shown via `Position.state`, not a computed fill
percentage.** `Position` has no `trade_plan_id` foreign key back to the
`TradePlan` that carries `t1_percent`/`t2_percent`, so there is no
reliable way to look up which trade plan produced a given open position -
inventing a symbol-based guess would fabricate a precision this schema
doesn't have. The detail page instead shows a 4-step progress indicator
driven by the real, already fill-derived `state`
(OPEN→T1_FILLED→T2_FILLED→RUNNER→CLOSED), plus each real `ProtectiveOrder`'s
target price as "손절가"/"T1 목표가"/"T2 목표가".

### New capability: a real audit log for the emergency-stop screen

`GET /api/dashboard/risk-states/history` just reads back `risk_states`
(P18), which was already append-only - every automatic kill-switch
evaluation and every manual `activate_emergency_stop()`/
`clear_emergency_stop()` call already left a real row behind; this adds
no new writes, only a way to read the history that already existed. The
new `EmergencyStopPage` (`#/emergency`, linked from the home screen)
shows the real current status plus this real log, never a synthesized
activity feed.

### New shared component: press-and-hold confirmation

`HoldToConfirmButton` is the functional equivalent of the mockups'
"n초간 눌러 확인" slider - press-and-hold gives the same "can't fire on
an accidental tap" friction a drag slider does, without hand-rolling
pointer-drag physics for what is ultimately a single boolean outcome.
Used for "즉시 청산" and for activating/clearing 긴급정지 from the new
detail screen - both real, destructive, real-money-adjacent actions.
Releasing early cancels; nothing fires until the hold genuinely
completes.

### What P46 deliberately did not build

- **A literal drag slider** matching mockup 06's exact visual - a
  press-and-hold button gives the identical safety property (can't fire
  without sustained deliberate input) without hand-rolled drag-gesture
  math for a single boolean outcome.
- **A percentage-based T1/T2 fill progress bar** - see above; this
  schema has no reliable link from `Position` back to the `TradePlan`
  that would make that percentage real, so it isn't shown as one.
- **Retrofitting `ApprovalPage`'s existing 승인/거절 flow** with
  `HoldToConfirmButton` - that flow already has a real, tested PIN-gated
  confirmation step (mockup 06's underlying need); redesigning a working,
  tested confirmation flow in the same pass as introducing this
  project's first real manual SELL order was a larger change than this
  batch needed to make.

## What was deliberately not built

- **A full 6-tab IA rewrite** matching the mockups' 홈/레이더/승인대기/
  포지션/성과/설정 structure. The existing 7-tab structure (Radar/종목/
  추천/포지션/시장/성과/시스템) is fully real and tested; this pass kept
  it and applied the new visual system and capabilities on top, rather
  than risk breaking working functionality on a from-scratch navigation
  rebuild in the same pass.
- **A bespoke "추천 상세" full-screen detail page** matching mockup 04 -
  `RecommendationCard` already surfaces the same real entry/stop/target/
  reasons/risks data inline; a separate detail route is a natural, small
  follow-up rather than something this pass needed to duplicate.
- **ETF/ETN withdrawal-permission introspection** via a live broker API -
  not exposed by either broker's public API, so not something this
  project can honestly claim to check that way (see item 3 above).
