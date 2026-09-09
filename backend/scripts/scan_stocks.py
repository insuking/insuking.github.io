#!/usr/bin/env python3
"""Run a real KIS PRE-BREAKOUT stock scan (P23, extended in P25).

Real HTTP requests to KIS (requires `KIS_APP_KEY`/`KIS_APP_SECRET` - see
docs/KIS_SETUP.md). Read-only: writes nothing to the database yet - P23's
DB tables (`securities`, `radar_scores`, `radar_features`) exist (see
app/db/models.py) but persistence wiring is a fast-follow, not blocked on
anything here.

**Universe**: `STOCK_SCAN_SYMBOLS` (comma-separated KRX 6-digit codes) if
set, else a small default list of large, liquid KOSPI names - not the
full KOSPI/KOSDAQ universe. A real full-universe scan needs KIS's KRX
symbol master file, which this project has not built a verified
downloader/parser for yet (see app/stock_radar/scan.py's module
docstring) - seed `securities` by hand or extend this script once that
exists.

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
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.rest_client import KOSPI_INDEX_CODE, KisRestClient
from app.models.domain import Candle
from app.radar.regime import MarketRegime, classify_market_regime
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


if __name__ == "__main__":
    asyncio.run(run())
