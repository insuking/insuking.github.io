#!/usr/bin/env python3
"""P38: fetch real premarket macro data (S&P500, SOX, VIX, WTI oil,
USD/KRW) from Yahoo Finance's public chart API (no API key needed) and
persist today's `MacroRegime` snapshot for the 시장 탭's "해외 매크로" card.

Meant to run once daily around 08:20 KST, before KRX opens
(`scripts/scheduler.py`'s macro pass) - a read-only advisory signal a
human reviews each morning, never an automatic trade gate (see
`app/radar/macro_regime.py`'s module docstring for why).

Each of the five symbols is fetched independently; a single failure
(rate limit, a temporarily unavailable symbol, a network hiccup)
degrades that one metric to `None` rather than aborting the whole
snapshot - partial real data beats no data, and
`app/radar/macro_regime.py` already treats `None` as "skip this signal,"
never a fabricated 0.

**Live-network test status**: like this project's other public-API
integrations (see `scan_crypto.py`'s own Upbit real-connection test
history), this deployment environment's outbound egress may be
restricted to an allowlist that does not include
query1.finance.yahoo.com - if so, a live call against this endpoint has
not been exercised from that environment, and the parsing logic is
unit-tested against Yahoo's documented chart-API JSON shape instead
(tests/backend/test_market_macro_rest_client.py). Verify against the
real endpoint once deployed somewhere with open egress (a normal Docker
Compose host, unlike a sandboxed dev container, typically has this).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

sys.path.insert(0, ".")

import httpx

from app.core.config import get_settings
from app.db.session import session_scope
from app.integrations.market_macro.errors import MarketMacroApiError
from app.integrations.market_macro.rest_client import MacroQuote, MarketMacroRestClient
from app.radar.macro_persistence import persist_macro_snapshot
from app.radar.macro_regime import MacroReading, classify_macro_regime


async def _fetch_quote(rest: MarketMacroRestClient, symbol: str, label: str) -> MacroQuote | None:
    try:
        return await rest.get_quote(symbol)
    except (MarketMacroApiError, httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
        print(f"WARNING: could not fetch {label} ({symbol}): {exc!r}")
        return None


async def run() -> None:
    settings = get_settings()
    observed_at = datetime.now(UTC)

    async with httpx.AsyncClient(base_url=settings.macro_rest_base_url, timeout=15.0) as client:
        rest = MarketMacroRestClient(client)
        sp500 = await _fetch_quote(rest, settings.macro_sp500_symbol, "S&P500")
        sox = await _fetch_quote(rest, settings.macro_sox_symbol, "SOX")
        vix = await _fetch_quote(rest, settings.macro_vix_symbol, "VIX")
        oil = await _fetch_quote(rest, settings.macro_oil_symbol, "WTI 유가")
        usdkrw = await _fetch_quote(rest, settings.macro_usdkrw_symbol, "USD/KRW")

    reading = MacroReading(
        sp500_change_pct=sp500.change_pct if sp500 else None,
        sox_change_pct=sox.change_pct if sox else None,
        vix_level=vix.price if vix else None,
        oil_change_pct=oil.change_pct if oil else None,
        usdkrw_change_pct=usdkrw.change_pct if usdkrw else None,
    )
    regime, headline = classify_macro_regime(reading)

    async with session_scope() as session:
        await persist_macro_snapshot(session, reading, regime, headline, observed_at)
        await session.commit()

    print(f"Macro check complete: {regime.value} - {headline}")


if __name__ == "__main__":
    asyncio.run(run())
