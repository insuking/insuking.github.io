#!/usr/bin/env python3
"""Run a real KIS PRE-BREAKOUT stock scan (P23, extended in P25/P26).

Real HTTP requests to KIS (requires `KIS_APP_KEY`/`KIS_APP_SECRET` - see
docs/KIS_SETUP.md). Now persists results: `securities` (upsert) and
`radar_scores` (one row per symbol per run) via
`app/stock_radar/persistence.py`'s `persist_scan_results()` -
`radar_features` is still not written (see that module's docstring for
why). If the DB write fails for any reason (unreachable Postgres, schema
drift), this script prints a warning and still shows the scan results -
persistence failing must never hide a real, already-computed scan.

**Universe**: three ways, in priority order -
1. `STOCK_SCAN_SYMBOLS` (comma-separated KRX 6-digit codes), if set.
2. `STOCK_SCAN_UNIVERSE=FULL` (P30) - the real KOSPI+KOSDAQ universe from
   KIS's KRX symbol master file (`app/integrations/kis/krx_master.py`),
   ranked by previous-day volume and capped at `STOCK_SCAN_TOP_N_PER_MARKET`
   (default 40) per market - not every listed symbol, since KIS's confirmed
   ~2 req/sec rate limit makes scanning the full multi-thousand-symbol
   universe impractical in one run. Falls back to the default list below if
   the master-file fetch fails for any reason.
3. Otherwise, a small default list of large, liquid KOSPI names.
`securities` rows are created automatically for whatever symbols this
script scans, no manual seeding needed.

**Benchmark**: this script attempts a real KOSPI index fetch via
`KisRestClient.get_index_daily_prices()` - confirmed working by a real
docker-compose run (2026-09), see docs/KIS_SETUP.md. If that call ever
fails (network, a future KIS-side change), this script falls back to a
flat placeholder benchmark and prints a clear warning rather than
crashing the whole scan.

**Institutional flow** (P25): each symbol's score also tries to include a
12-point `institutional_flow` factor (외국인+기관 순매수) via
`KisRestClient.get_investor_trend()` - not yet confirmed against a live
response from this project's own credentials, unlike the benchmark above.
`scan_stock_universe()` degrades that one symbol back to the 65-point
price/volume-only ceiling (rather than crashing the scan) if the call
fails - see that function's docstring.

**Market regime** (P26): prints the KOSPI regime via the existing P4
`classify_market_regime()` (the same function crypto's BTC-based regime
already reuses, see app/radar/crypto_features.py) against the real KOSPI
benchmark - no new logic needed, it already takes any index candle series.
Informational only here: RISK_OFF doesn't change any symbol's score, since
"is this a good setup" (radar) and "should I trade at all right now"
(entry filter) are deliberately separate per the master spec - the
approval flow (`app/approval/revalidation.py`) is where RISK_OFF actually
blocks something.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, ".")

import httpx

from app.core.config import get_settings
from app.db.session import session_scope
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.krx_master import (
    fetch_kosdaq_master,
    fetch_kospi_master,
    rank_tradable_by_liquidity,
)
from app.integrations.kis.rest_client import KOSPI_INDEX_CODE, KisRestClient
from app.models.domain import Candle, Market
from app.radar.candle_persistence import persist_candles
from app.radar.regime import MarketRegime, classify_market_regime
from app.stock_radar.persistence import persist_scan_results
from app.stock_radar.scan import scan_stock_universe

_DEFAULT_SYMBOLS = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "051910",  # LG화학
    "005380",  # 현대차
    "035420",  # NAVER
]
_HISTORY_DAYS = 200
_DEFAULT_FULL_UNIVERSE_TOP_N_PER_MARKET = 40


async def _full_universe_symbols(top_n_per_market: int) -> list[str]:
    """`STOCK_SCAN_UNIVERSE=FULL` path (P30) - real KOSPI+KOSDAQ symbols
    from the KRX master file (`app/integrations/kis/krx_master.py`) instead
    of `_DEFAULT_SYMBOLS`'s 5 hardcoded names. Ranked separately per market
    by previous-day volume (not merged into one cross-market sort - see
    that module's own docstring for why) and capped at `top_n_per_market`
    each, since KIS's confirmed ~2 req/sec rate limit makes scanning the
    full multi-thousand-symbol universe impractical in one run.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        kospi_rows, kosdaq_rows = await asyncio.gather(
            fetch_kospi_master(client), fetch_kosdaq_master(client)
        )
    kospi_top = rank_tradable_by_liquidity(kospi_rows, top_n_per_market)
    kosdaq_top = rank_tradable_by_liquidity(kosdaq_rows, top_n_per_market)
    print(
        f"Using real KRX master-file universe: {len(kospi_top)} KOSPI + {len(kosdaq_top)} KOSDAQ "
        f"symbols (top {top_n_per_market} each by previous-day volume).\n"
    )
    return [r.symbol for r in kospi_top] + [r.symbol for r in kosdaq_top]


def _flat_benchmark(length: int) -> list[Candle]:
    now = datetime.now(UTC)
    return [
        Candle(
            symbol="KOSPI_PLACEHOLDER",
            interval="1d",
            open=1000.0,
            high=1005.0,
            low=995.0,
            close=1000.0,
            volume=1.0,
            open_time=now - timedelta(days=length - i),
            close_time=now - timedelta(days=length - i - 1),
        )
        for i in range(length)
    ]


async def run() -> None:
    settings = get_settings()
    if not settings.kis_configured:
        print("KIS_APP_KEY/KIS_APP_SECRET are not set - see docs/KIS_SETUP.md. Nothing to scan yet.")
        return

    symbols_raw = os.environ.get("STOCK_SCAN_SYMBOLS")
    if symbols_raw:
        symbols = [s.strip() for s in symbols_raw.split(",")]
    elif os.environ.get("STOCK_SCAN_UNIVERSE", "").upper() == "FULL":
        top_n_per_market = int(os.environ.get("STOCK_SCAN_TOP_N_PER_MARKET", _DEFAULT_FULL_UNIVERSE_TOP_N_PER_MARKET))
        try:
            symbols = await _full_universe_symbols(top_n_per_market)
        except (KisApiError, httpx.HTTPError, KeyError, ValueError) as exc:
            print(
                f"WARNING: KRX master-file fetch failed ({exc!r}) - falling back to the "
                f"{len(_DEFAULT_SYMBOLS)}-symbol default list. See "
                "app/integrations/kis/krx_master.py's docstring.\n"
            )
            symbols = _DEFAULT_SYMBOLS
    else:
        symbols = _DEFAULT_SYMBOLS

    end_date = datetime.now(UTC).strftime("%Y%m%d")
    start_date = (datetime.now(UTC) - timedelta(days=_HISTORY_DAYS)).strftime("%Y%m%d")

    async with httpx.AsyncClient(base_url=settings.kis_rest_base_url) as client:
        auth = KisAuth(client=client, settings=settings)
        rest = KisRestClient(client, auth)

        benchmark_is_real = True
        try:
            benchmark_candles = await rest.get_index_daily_prices(KOSPI_INDEX_CODE, start_date, end_date)
            if not benchmark_candles:
                raise KisApiError("KOSPI index fetch returned no candles")
            print(f"Using real KOSPI index benchmark ({len(benchmark_candles)} candles).\n")
        except (KisApiError, KeyError, ValueError) as exc:
            print(
                f"WARNING: real KOSPI index fetch failed ({exc!r}) - falling back to a flat "
                "placeholder benchmark. Relative-strength scores below are not trustworthy yet. "
                "See KisRestClient.get_index_daily_prices()'s docstring.\n"
            )
            benchmark_candles = _flat_benchmark(_HISTORY_DAYS)
            benchmark_is_real = False

        # P37: only ever persist the real fetch - the flat placeholder above
        # exists so scoring can still run, never to be mistaken for a real
        # market read by the 시장 tab's regime display.
        if benchmark_is_real:
            async with session_scope() as session:
                await persist_candles(session, benchmark_candles)
                await session.commit()

        regime = classify_market_regime(benchmark_candles)
        regime_label = {
            MarketRegime.RISK_ON: "RISK_ON (상승 추세 - 돌파 시도에 우호적)",
            MarketRegime.RISK_OFF: "RISK_OFF (하락 추세 - 신규 진입에 비우호적)",
            MarketRegime.NEUTRAL: "NEUTRAL (혼조 - 방향성 불명확)",
        }[regime]
        print(f"시장 상황 (KOSPI 기준): {regime_label}\n")

        results, names = await scan_stock_universe(
            rest,
            symbols=symbols,
            benchmark_candles=benchmark_candles,
            start_date=start_date,
            end_date=end_date,
        )

    if not results:
        print("No candidates scored - either no symbols had enough history, or none exist.")
        return

    for r in results:
        label = f"{r.symbol} ({names[r.symbol]})" if r.symbol in names else r.symbol
        print(f"{label}: {r.total_score:.1f} / {r.max_available:.0f}")
        for factor in r.positive:
            print(f"  + {factor.detail}")
        for factor in r.negative:
            print(f"  - {factor.detail}")

    try:
        async with session_scope() as session:
            run_id = await persist_scan_results(session, results, names, market=Market.KOSPI)
        print(f"\nPersisted {len(results)} score(s) to the database (scan_run_id={run_id}).")
    except Exception as exc:  # noqa: BLE001 - a DB failure must not hide the scan results already printed above
        print(f"\nWARNING: failed to persist scan results to the database ({exc!r}).")


if __name__ == "__main__":
    asyncio.run(run())
