"""Upbit public REST client (P7): secondary price verification + candles.

No API key needed. Two roles:

1. `get_ticker_price` + `verify_price_consistency`: a periodic REST snapshot
   to cross-check against the WS feed's last price, catching a WS stream
   that has silently drifted or gone stale without technically
   disconnecting (see ws_client.py's staleness watchdog for the other half
   of that story).
2. `get_candles`: Upbit's public WebSocket has no real-time candle channel
   ("candle where appropriate" per docs/MASTER_SPEC.md P7 - it isn't
   appropriate over WS here, since Upbit doesn't offer one; REST is the
   real mechanism).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.integrations.upbit.errors import UpbitApiError
from app.models.domain import Candle


class UpbitRestClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_ticker_price(self, market: str) -> float:
        data = await self._get("/v1/ticker", params={"markets": market})
        return float(data[0]["trade_price"])

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
