#!/usr/bin/env python3
"""Run a real KIS PRE-BREAKOUT stock scan (P23).

Real HTTP requests to KIS (requires `KIS_APP_KEY`/`KIS_APP_SECRET` - see
docs/KIS_SETUP.md; this project has none provisioned yet, so this script
cannot be run for real until you provision them). Read-only: writes
nothing to the database yet - P23's DB tables (`securities`,
`radar_scores`, `radar_features`) exist (see app/db/models.py) but
persistence wiring is a fast-follow, not blocked on anything here.

**Universe**: `STOCK_SCAN_SYMBOLS` (comma-separated KRX 6-digit codes) if
set, else a small default list of large, liquid KOSPI names - not the
full KOSPI/KOSDAQ universe. A real full-universe scan needs KIS's KRX
symbol master file, which this project has not built a verified
downloader/parser for yet (see app/stock_radar/scan.py's module
docstring) - seed `securities` by hand or extend this script once that
exists.

**Benchmark**: this script now attempts a real KOSPI index fetch via
`KisRestClient.get_index_daily_prices()` (see that method's docstring -
still not independently verified against real KIS servers as of this
writing). If that call fails for any reason (unverified field layout,
KIS error, network), this script falls back to a flat placeholder
benchmark and prints a clear warning rather than crashing the whole scan
- in that fallback case every score's "시장 상대강도" component still
reads as the stock's own raw return rather than a true excess-over-
benchmark figure. Once a real run confirms the index fetch works, this
fallback path should stop triggering in practice; it stays in place as
a safety net either way.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, ".")

import httpx

from app.core.config import get_settings
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.rest_client import KOSPI_INDEX_CODE, KisRestClient
from app.models.domain import Candle
from app.stock_radar.scan import scan_stock_universe

_DEFAULT_SYMBOLS = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "051910",  # LG화학
    "005380",  # 현대차
    "035420",  # NAVER
]
_HISTORY_DAYS = 200


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
    symbols = [s.strip() for s in symbols_raw.split(",")] if symbols_raw else _DEFAULT_SYMBOLS

    end_date = datetime.now(UTC).strftime("%Y%m%d")
    start_date = (datetime.now(UTC) - timedelta(days=_HISTORY_DAYS)).strftime("%Y%m%d")

    async with httpx.AsyncClient(base_url=settings.kis_rest_base_url) as client:
        auth = KisAuth(client=client, settings=settings)
        rest = KisRestClient(client, auth)

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

        results = await scan_stock_universe(
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
        print(f"{r.symbol}: {r.total_score:.1f} / {r.max_available:.0f}")
        for factor in r.positive:
            print(f"  + {factor.detail}")
        for factor in r.negative:
            print(f"  - {factor.detail}")


if __name__ == "__main__":
    asyncio.run(run())
