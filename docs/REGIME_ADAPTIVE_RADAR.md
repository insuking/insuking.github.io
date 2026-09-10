# Regime-Adaptive Radar (P34-P36)

This extends the stock radar from "rank candidates by a single score" to
three additional, independent signals layered on top: how a symbol's
strength interacts with the market's own direction (P34), whether it's
already moved too far to chase (P35), and a final BUY/WATCH/NO_BUY/
NO_TRADE_DAY call that treats "nothing worth buying today" as a normal,
successful outcome rather than an absence to work around (P36).

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

These two functions exist and are fully tested but are **not yet wired
into `reconfirm_entries.py`'s persisted output** - see Known gaps below.

## Known gaps - explicitly out of scope this pass, not silently skipped

The original request asked for several pieces this project has no real
data source for, or that need infrastructure well beyond what a single
pass can honestly build and test. Listed here rather than faked:

- **Leader-Laggard Engine** (분석 선두주 대비 후발 공급망 종목 찾기): needs
  a supply-chain/sector-peer mapping data source (same customer, same
  process, same supply chain) this project has never had access to.
  Fabricating peer relationships would be worse than not having the
  feature.
- **RS_5m/RS_15m/RS_30m/RS_60m intraday persistence**: the stock radar
  (P23 onward) is built entirely on *daily* candles - there is no
  intraday tick/minute-bar store for stocks the way the crypto radar has
  for Upbit. Building one is a real, separate phase, not a field to add
  here.
- **08:20 daily macro-regime check** (미국장/SOX/VIX/유가/환율): no
  integration exists for any of those data sources. `reconfirm_entries.py`
  already documents that its own output only means anything during real
  KRX hours; a pre-market macro read is a genuinely separate integration.
- **Weekly weight auto-retuning / labeling learning loop**: `regime_
  relative_strength.label` and a symbol's eventual outcome give the raw
  material for this, but the retuning process itself needs real trading
  history accumulated over real weeks - there's nothing to learn from on
  day one, and building the mechanism without real data to validate it
  against would be guessing at a shape, not implementing a working loop.
- **Bad Trade Avoidance Rate / Chase Avoidance Rate / No-Trade Accuracy
  KPIs**: these require actual historical trade outcomes tracked over
  time. The crypto radar has a backtest harness (P10); the stock radar
  does not. `decide_entry_state()`'s persisted reasoning (once wired -
  see below) is the raw material a future backtest phase would need, but
  computing the KPIs themselves needs that harness built first.
- **P36's decision engine is not yet wired into `reconfirm_entries.py`'s
  persisted output** - `decide_entry_state()`/`decide_daily_state()` are
  built, tested, and ready, but connecting them to a persisted per-run
  "today's call" (and a dashboard card showing it) is the natural next
  step, deliberately left for a follow-up pass rather than rushed in
  alongside the P34/P35 wiring in this one.
