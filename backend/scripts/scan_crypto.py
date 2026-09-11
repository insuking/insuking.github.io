#!/usr/bin/env python3
"""Run a real Upbit crypto market scan and persist up to 5 recommendations (P23).

Unlike `seed_demo_data.py`, this makes real HTTP requests to Upbit's public
REST API (`UPBIT_REST_BASE_URL`, no API key needed - see docs/UPBIT_NOTES.md)
and computes every signal from that real data through the already-tested
P4/P8/P9 pure functions (app/scan/crypto_scan.py). Nothing here is sample or
placeholder data; a quiet market can legitimately produce fewer than 5
recommendations, or zero - this never pads the result to hit a count.

`account_buying_power` is the one number this script cannot get from Upbit:
this phase has no crypto account-balance integration (Upbit's authenticated
endpoints are P15 order placement, not a balance query used here), so it
only affects this scan's own position-size/risk-amount math and must be
supplied via `SCAN_ACCOUNT_BUYING_POWER` (KRW). The unset default is a
clearly-fake placeholder, not a real balance - see the printed warning below.

Every persisted row's id is prefixed `scan-crypto-`, and a run first deletes
all previous `scan-crypto-%` rows, so this is safe to re-run repeatedly
(same idempotent-replace pattern as seed_demo_data.py) and never accumulates
stale recommendations from an earlier scan.

**P37**: also fetches and persists ~25 real daily BTC candles
(`UpbitRestClient.get_daily_candles()`) to the generic `candles` table via
`app.radar.candle_persistence.persist_candles()` - a real, continuously
refreshed feed for the 시장 tab's BTC regime read, replacing what used to
only work because `seed_demo_data.py`'s demo candles happened to still be
within the 20-day moving-average window. Deliberately separate from the
1-minute candles `scan_crypto_market()` fetches internally for its own
RVOL/breakout math - a 20-period moving average over 1-minute bars would
read a ~20-minute blip, not the daily-trend "is BTC safe right now" this
tab is actually answering.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, ".")

import httpx
from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models import Recommendation as RecommendationRow
from app.db.session import session_scope
from app.integrations.upbit.errors import UpbitApiError
from app.integrations.upbit.rest_client import UpbitRestClient
from app.radar.candle_persistence import persist_candles
from app.scan.crypto_scan import BENCHMARK_MARKET, scan_crypto_market

_DEFAULT_BUYING_POWER = 10_000_000.0  # KRW placeholder - see module docstring
_REGIME_CANDLE_COUNT = 25  # comfortably covers app.radar.regime's 20-day moving average


async def _clear_previous() -> None:
    async with session_scope() as session:
        await session.execute(delete(RecommendationRow).where(RecommendationRow.id.like("scan-crypto-%")))
        await session.commit()


async def run() -> None:
    settings = get_settings()

    buying_power_raw = os.environ.get("SCAN_ACCOUNT_BUYING_POWER")
    if buying_power_raw is None:
        print(
            f"SCAN_ACCOUNT_BUYING_POWER not set - using a {_DEFAULT_BUYING_POWER:,.0f} KRW "
            "placeholder for position sizing. Set it to your real buying power for accurate sizing."
        )
        account_buying_power = _DEFAULT_BUYING_POWER
    else:
        account_buying_power = float(buying_power_raw)

    await _clear_previous()

    async with httpx.AsyncClient(base_url=settings.upbit_rest_base_url) as client:
        rest = UpbitRestClient(client)
        recommendations = await scan_crypto_market(rest, account_buying_power=account_buying_power)

        try:
            regime_candles = await rest.get_daily_candles(BENCHMARK_MARKET, count=_REGIME_CANDLE_COUNT)
        except (UpbitApiError, httpx.HTTPError, KeyError, ValueError) as exc:
            print(f"WARNING: could not fetch real BTC daily candles for the 시장 tab's regime read ({exc!r}).")
            regime_candles = []

    if regime_candles:
        async with session_scope() as session:
            await persist_candles(session, regime_candles)
            await session.commit()

    async with session_scope() as session:
        for i, rec in enumerate(recommendations):
            session.add(
                RecommendationRow(
                    id=f"scan-crypto-{i}",
                    symbol=rec.symbol,
                    name=rec.name,
                    asset_type=rec.asset_type.value,
                    score=rec.score,
                    state=rec.state,
                    entry_low=rec.entry_low,
                    entry_high=rec.entry_high,
                    stop_price=rec.stop_price,
                    t1_price=rec.t1_price,
                    t1_percent=rec.t1_percent,
                    t2_price=rec.t2_price,
                    t2_percent=rec.t2_percent,
                    runner_percent=rec.runner_percent,
                    expected_max_loss=rec.expected_max_loss,
                    risk_reward=rec.risk_reward,
                    reasons=json.dumps(rec.reasons, ensure_ascii=False),
                    risks=json.dumps(rec.risks, ensure_ascii=False),
                    created_at=rec.created_at,
                    expires_at=rec.expires_at,
                )
            )
        await session.commit()

    if not recommendations:
        print("Scan complete: no eligible breakout candidates found in the current KRW market.")
        return

    print(f"Scan complete: {len(recommendations)} real crypto recommendation(s) saved.")
    for rec in recommendations:
        print(f"  {rec.symbol}  score={rec.score:.1f}  state={rec.state}  entry={rec.entry_low:,.2f}")


if __name__ == "__main__":
    asyncio.run(run())
