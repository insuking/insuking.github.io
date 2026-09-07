"""Upbit public REST client: secondary price verification + candles (P7),
KRW market universe (P9).

No API key needed. Roles:

1. `get_ticker_price` + `verify_price_consistency`: a periodic REST snapshot
   to cross-check against the WS feed's last price, catching a WS stream
   that has silently drifted or gone stale without technically
   disconnecting (see ws_client.py's staleness watchdog for the other half
   of that story).
2. `get_candles`: Upbit's public WebSocket has no real-time candle channel
   ("candle where appropriate" per docs/MASTER_SPEC.md P7 - it isn't
   appropriate over WS here, since Upbit doesn't offer one; REST is the
   real mechanism).
3. `get_krw_market_universe` (P9): the full tradable KRW-* symbol list the
   crypto radar ranks into TOP200/30/5 - see docs/UPBIT_NOTES.md for what
   was and wasn't independently verified about this endpoint's response
   shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.integrations.upbit.errors import UpbitApiError
from app.models.domain import Candle


@dataclass
class TickerSummary:
    market: str
    trade_price: float
    acc_trade_price_24h: float


class UpbitRestClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_krw_market_universe(self) -> list[str]:
        """All tradable `KRW-*` market symbols (verified via pyupbit's `get_tickers()`:
        `GET /v1/market/all`, filtering the `market` field by prefix - see
        docs/UPBIT_NOTES.md).
        """
        data = await self._get("/v1/market/all", params={"isDetails": "false"})
        return [item["market"] for item in data if item["market"].startswith("KRW-")]

    async def get_ticker_price(self, market: str) -> float:
        data = await self._get("/v1/ticker", params={"markets": market})
        return float(data[0]["trade_price"])

    async def get_tickers_summary(self, markets: list[str]) -> list[TickerSummary]:
        """One batched snapshot (price + 24h accumulated trade value) across
        many markets - `/v1/ticker` accepts a comma-separated `markets` list
        in a single request. Used to rank the full KRW universe by liquidity
        before spending a per-market `get_candles()` call on only the most
        active ones (see app/scan/crypto_scan.py)."""
        if not markets:
            return []
        data = await self._get("/v1/ticker", params={"markets": ",".join(markets)})
        return [
            TickerSummary(
                market=item["market"],
                trade_price=float(item["trade_price"]),
                acc_trade_price_24h=float(item["acc_trade_price_24h"]),
            )
            for item in data
        ]

    async def get_candles(self, market: str, unit_minutes: int = 1, count: int = 200) -> list[Candle]:
        data = await self._get(
            f"/v1/candles/minutes/{unit_minutes}", params={"market": market, "count": count}
        )
        return [self._to_candle(item, market, unit_minutes) for item in data]

    def _to_candle(self, item: dict, market: str, unit_minutes: int) -> Candle:
        open_time = datetime.fromisoformat(item["candle_date_time_utc"]).replace(tzinfo=UTC)
        return Candle(
            symbol=market,
            interval=f"{unit_minutes}m",
            open=float(item["opening_price"]),
            high=float(item["high_price"]),
            low=float(item["low_price"]),
            close=float(item["trade_price"]),
            volume=float(item["candle_acc_trade_volume"]),
            open_time=open_time,
            close_time=open_time + timedelta(minutes=unit_minutes),
        )

    async def _get(self, path: str, params: dict[str, str | int] | None = None) -> list[dict]:
        response = await self._client.get(path, params=params)
        if response.is_error:
            try:
                body = response.json()
            except ValueError:
                body = {}
            error = body.get("error") if isinstance(body.get("error"), dict) else {}
            raise UpbitApiError(response.status_code, error.get("name"), error.get("message"))
        return response.json()


def verify_price_consistency(ws_price: float, rest_price: float, max_deviation: float = 0.02) -> bool:
    """True if `ws_price` agrees with the REST snapshot within `max_deviation` (fractional, e.g. 0.02 = 2%)."""
    if rest_price <= 0:
        return False
    return abs(ws_price - rest_price) / rest_price <= max_deviation
