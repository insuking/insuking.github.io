#!/usr/bin/env python3
"""Run a real KIS PRE-BREAKOUT stock scan (P23, extended in P25/P26/P39).

Real HTTP requests to KIS (requires `KIS_APP_KEY`/`KIS_APP_SECRET` - see
docs/KIS_SETUP.md). Now persists results: `securities` (upsert) and
`radar_scores` (one row per symbol per run) via
`app/stock_radar/persistence.py`'s `persist_scan_results()` -
`radar_features` is still not written (see that module's docstring for
why). If the DB write fails for any reason (unreachable Postgres, schema
drift), this script prints a warning and still shows the scan results -
persistence failing must never hide a real, already-computed scan.

**Universe**: three ways, in priority order -
1. `STOCK_SCAN_SYMBOLS` (comma-separated KRX 6-digit codes), if set -
   for manual testing of specific symbols.
2. `STOCK_SCAN_UNIVERSE=DEFAULT` - the small 5-symbol list below, for
   fast local dev iteration when you don't want to wait on a real
   KRX master-file fetch.
3. Otherwise (the actual default, P39) - the **real, full** KOSPI+KOSDAQ
   universe from KIS's KRX symbol master file
   (`app/integrations/kis/krx_master.py`), tradable-filtered and ordered
   by previous-day volume, then **rotated** through
   `STOCK_SCAN_CHUNK_SIZE_PER_MARKET`-sized slices per market
   (`app/radar/universe_rotation.py`) so that every tradable symbol on
   both markets actually gets scanned - not just the same handful
   forever. One run can't cover several thousand symbols against KIS's
   confirmed ~2 req/sec rate limit (see that module's own docstring),
   so successive scheduler runs (`SCHEDULER_STOCK_INTERVAL_SECONDS`
   apart) each cover the next chunk, cycling back to the start once
   every symbol has been scanned. Falls back to the 5-symbol default
   list if the master-file fetch fails for any reason.
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
from app.radar.universe_rotation import select_rotation_chunk
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
_DEFAULT_STOCK_SCAN_CHUNK_SIZE_PER_MARKET = 250
_DEFAULT_SCHEDULER_STOCK_INTERVAL_SECONDS = 1800  # must match scripts/scheduler.py's own default


async def _full_universe_symbols(chunk_size_per_market: int, now: datetime, interval_seconds: int) -> list[str]:
    """Default universe path (P39, extends P30) - the real KOSPI+KOSDAQ
    universe from the KRX master file (`app/integrations/kis/krx_master.py`),
    tradable-filtered and ordered by previous-day volume (most liquid
    first per market, not merged into one cross-market sort - see that
    module's own docstring for why), then rotated through
    `chunk_size_per_market`-sized slices per market via
    `select_rotation_chunk()` so that every tradable symbol on both
    markets actually gets scanned over successive runs, instead of the
    same top-N-by-liquidity slice forever. `now`/`interval_seconds`
    should match how often this script is actually invoked (the
    scheduler's `SCHEDULER_STOCK_INTERVAL_SECONDS`) so each run advances
    to the next chunk rather than re-scanning the current one.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        kospi_rows, kosdaq_rows = await asyncio.gather(
            fetch_kospi_master(client), fetch_kosdaq_master(client)
        )
    kospi_all = rank_tradable_by_liquidity(kospi_rows, len(kospi_rows))
    kosdaq_all = rank_tradable_by_liquidity(kosdaq_rows, len(kosdaq_rows))
    kospi_chunk = select_rotation_chunk(kospi_all, chunk_size_per_market, now, interval_seconds)
    kosdaq_chunk = select_rotation_chunk(kosdaq_all, chunk_size_per_market, now, interval_seconds)
    kospi_chunks_total = max(1, -(-len(kospi_all) // chunk_size_per_market)) if kospi_all else 0
    kosdaq_chunks_total = max(1, -(-len(kosdaq_all) // chunk_size_per_market)) if kosdaq_all else 0
    print(
        f"Using real KRX master-file universe (rotating): {len(kospi_chunk)}/{len(kospi_all)} tradable "
        f"KOSPI symbols this run (~{kospi_chunks_total} chunks to cover the whole market) + "
        f"{len(kosdaq_chunk)}/{len(kosdaq_all)} tradable KOSDAQ symbols "
        f"(~{kosdaq_chunks_total} chunks) - every tradable symbol gets scanned roughly once every "
        f"{max(kospi_chunks_total, kosdaq_chunks_total, 1)} stock-pass cycles "
        f"({interval_seconds}s apart).\n"
    )
    return [r.symbol for r in kospi_chunk] + [r.symbol for r in kosdaq_chunk]


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
    elif os.environ.get("STOCK_SCAN_UNIVERSE", "").upper() == "DEFAULT":
        symbols = _DEFAULT_SYMBOLS
    else:
        chunk_size_per_market = int(
            os.environ.get("STOCK_SCAN_CHUNK_SIZE_PER_MARKET", _DEFAULT_STOCK_SCAN_CHUNK_SIZE_PER_MARKET)
        )
        interval_seconds = int(
            os.environ.get("SCHEDULER_STOCK_INTERVAL_SECONDS", _DEFAULT_SCHEDULER_STOCK_INTERVAL_SECONDS)
        )
        try:
            symbols = await _full_universe_symbols(chunk_size_per_market, datetime.now(UTC), interval_seconds)
        except (KisApiError, httpx.HTTPError, KeyError, ValueError) as exc:
            print(
                f"WARNING: KRX master-file fetch failed ({exc!r}) - falling back to the "
                f"{len(_DEFAULT_SYMBOLS)}-symbol default list. See "
                "app/integrations/kis/krx_master.py's docstring.\n"
            )
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
