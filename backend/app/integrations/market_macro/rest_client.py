"""Thin client over Yahoo Finance's public `/v8/finance/chart/{symbol}`
endpoint (P38) - no API key needed, same "public, no auth" tier as
`app.integrations.upbit.rest_client.UpbitRestClient`. Used only for the
daily 08:20 KST premarket macro check (`scripts/scan_macro.py`); nothing
else in this project depends on it.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .errors import MarketMacroApiError


@dataclass(frozen=True)
class MacroQuote:
    """One symbol's latest real close and previous close - `change_pct`
    is derived, never fetched separately, so it can never disagree with
    `price`/`previous_close`."""

    symbol: str
    price: float
    previous_close: float

    @property
    def change_pct(self) -> float:
        return (self.price - self.previous_close) / self.previous_close * 100.0


class MarketMacroRestClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_quote(self, symbol: str) -> MacroQuote:
        """Raises `MarketMacroApiError` on a non-2xx response, an
        API-reported error, or a response with no usable price data -
        never returns a fabricated or zero-filled quote.
        """
        response = await self._client.get(
            f"/v8/finance/chart/{symbol}", params={"range": "5d", "interval": "1d"}
        )
        if response.is_error:
            raise MarketMacroApiError(symbol, response.status_code, "http_error")

        body = response.json()
        chart = body.get("chart") or {}
        if chart.get("error"):
            raise MarketMacroApiError(symbol, response.status_code, str(chart["error"]))

        results = chart.get("result") or []
        if not results:
            raise MarketMacroApiError(symbol, response.status_code, "empty_result")

        result = results[0]
        meta = result.get("meta") or {}
        price = meta.get("regularMarketPrice")
        previous_close = meta.get("previousClose") or meta.get("chartPreviousClose")

        if price is None or previous_close is None or previous_close == 0:
            price, previous_close = self._closes_from_series(result)

        if price is None or previous_close is None or previous_close == 0:
            raise MarketMacroApiError(symbol, response.status_code, "no_usable_price_data")

        return MacroQuote(symbol=symbol, price=float(price), previous_close=float(previous_close))

    @staticmethod
    def _closes_from_series(result: dict) -> tuple[float | None, float | None]:
        """Fallback for a response whose `meta` block is missing
        `previousClose`/`chartPreviousClose` - the last two non-null
        daily closes in the requested 5-day window give the same answer.
        """
        quotes = (result.get("indicators") or {}).get("quote") or [{}]
        closes = quotes[0].get("close") or []
        non_null = [c for c in closes if c is not None]
        if len(non_null) < 2:
            return None, None
        return float(non_null[-1]), float(non_null[-2])
