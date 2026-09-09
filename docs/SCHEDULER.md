# Scheduler (P32)

## The gap this closes

`scripts/scan_crypto.py`, `scripts/scan_stocks.py`, and
`scripts/reconfirm_entries.py` all worked correctly from the moment they
were built (P23/P27/P31) - but nothing ever *ran* them in a real
deployment. `docker compose up` brings up `postgres`/`redis`/`backend`/
`frontend` and then just sits there; someone has to
`docker compose exec backend python scripts/scan_crypto.py` by hand for
even one `Recommendation` row to exist. In practice nobody remembered to
do that, so the "추천" tab and Home's "TOP 추천" stayed empty in a real
deployment even though every piece of the pipeline behind them was
already correct and tested. `scripts/scheduler.py` is the missing "run
this periodically" piece.

## What it does, and does not, do

**Does**: on a loop, runs the crypto scan every
`SCHEDULER_CRYPTO_INTERVAL_SECONDS` (default 300s = 5 min - Upbit's
public REST API, no key needed, and crypto trades 24/7), and the stock
scan + reconfirm pass every `SCHEDULER_STOCK_INTERVAL_SECONDS` (default
1800s = 30 min) **only inside real KRX trading hours** (09:00-15:30 KST,
Mon-Fri - see `app/scheduler/market_hours.py`). This is exactly what
running those three scripts by hand already did - real market data in,
scored `Recommendation` rows persisted, nothing fabricated.

**Does not**: create an `Approval`, send a Kakao notification, or place
an order. A human still has to open the app, see the recommendation on
the 추천 tab, and tap 승인 through the existing Kakao-approval flow
before anything executes. The project's standing "never fully
autonomous" rule is untouched - this automates read-only market
analysis (scan + score + persist a candidate), not execution.

## Running it

Docker Compose (`docker-compose.yml`) has a `scheduler` service that
builds from the same image as `backend` and runs
`python scripts/scheduler.py` instead of `uvicorn`. It waits for
`backend` to be healthy first (so Alembic migrations have already run)
and shares the same `.env` file, so `KIS_APP_KEY`/`KIS_APP_SECRET` and
`STOCK_SCAN_ACCOUNT_BUYING_POWER`/`SCAN_ACCOUNT_BUYING_POWER` (see
`docs/KIS_SETUP.md` and `scripts/scan_crypto.py`'s own docstring) work
the same way they already did when run by hand. It starts automatically
with `docker compose up --build -d` - no extra step needed.

Both scan scripts already no-op cleanly and print a message when
`KIS_APP_KEY`/`KIS_APP_SECRET` aren't set, so the scheduler is safe to
run before KIS credentials are configured - crypto recommendations will
still appear from the very first cycle; stock recommendations will start
appearing once KIS credentials are added to `.env` and the stack is
restarted.

## Known limitation: no KRX holiday calendar

`is_krx_trading_hours()` only checks the daily 09:00-15:30 KST window
and the day of the week - it does not know about KRX public holidays
(Lunar New Year, Chuseok, etc.), because no holiday-calendar source is
wired into this project. On a market holiday the scheduler will still
attempt the stock scan + reconfirm pass a few times; both scripts
degrade safely against a market that isn't actually trading (a stale
quote, an unchanged daily candle) rather than crash or fabricate a
recommendation, so the cost of getting this wrong is a handful of wasted
cycles, not a bad recommendation. Wiring a real holiday calendar is a
reasonable follow-up if this turns out to matter in practice.
