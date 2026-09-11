# SmartCoin UI Redesign (P45)

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

### New capability: manual emergency stop

The home screen's red "긴급정지" button calls `POST
/api/dashboard/emergency-stop` (and `/clear` to reverse it) - both
Kakao-session-gated the same way `/api/approvals`' endpoints are. Rather
than building a parallel kill-switch mechanism, this inserts a new
`RiskStateRow` with `kill_switch_active` forced on/off (numeric fields
carried forward from the latest real state) - `RiskService.
should_block_new_trades()` (P18) already reads "latest row by `as_of`"
as current, so the effect is immediate with zero new blocking logic.

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
