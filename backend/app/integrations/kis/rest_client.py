"""KIS REST client: domestic stock current-price snapshot (P3) and daily
OHLCV history (P23).

現재가 조회 (`/uapi/domestic-stock/v1/quotations/inquire-price`) was P3's
one endpoint; order placement is a later phase (P15) and must not exist yet
per the master spec's "implement only the active phase" rule.

Note on timestamps: the current-price snapshot endpoint does not return an
exchange-side transaction time, only current values - unlike the WebSocket
tick feed (`ws_client.py`), which carries a real `stck_cntg_hour` per trade.
So `exchange_ts` here is set equal to `received_ts` rather than fabricated;
callers needing true exchange-vs-received latency should use the WS stream.

`get_daily_prices()` (P23) is `inquire-daily-itemchartprice` - the field
names and request params below are NOT independently verified this session
(KIS's docs portal and `github.com/koreainvestment/open-trading-api` are
both unreachable from this sandbox, and `KIS_APP_KEY`/`KIS_APP_SECRET`
aren't provisioned yet - see docs/KIS_SETUP.md); they match the endpoint's
long-standing, widely-used shape (the same one every open-source KIS client
library targets), not a payload this session actually fetched. Re-verify
against a real response the first time real credentials exist, the same
"BLOCKED, not faked" discipline `test_kis_integration.py` already applies
to `get_quote()`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.models.domain import AssetType, Candle, Exchange, Market, Quote

_TR_ID_CURRENT_PRICE = "FHKST01010100"
_TR_ID_DAILY_CHART_PRICE = "FHKST03010100"


class KisRestClient:
    def __init__(self, client: httpx.AsyncClient, auth: KisAuth) -> None:
        self._client = client
        self._auth = auth

    async def get_quote(self, symbol: str, market: Market = Market.KOSPI) -> Quote:
        token = await self._auth.get_access_token()
        response = await self._client.get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            headers={
                "authorization": f"Bearer {token}",
                "appkey": self._auth.settings.kis_app_key,
                "appsecret": self._auth.settings.kis_app_secret,
                "tr_id": _TR_ID_CURRENT_PRICE,
                "custtype": "P",
            },
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
            },
        )
        body = response.json()
        if response.status_code != 200 or body.get("rt_cd") != "0":
            raise KisApiError(f"KIS inquire-price failed for {symbol}: {response.status_code} {body}")

        output = body["output"]
        now = datetime.now(UTC)
        return Quote(
            symbol=symbol,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KRX,
            market=market,
            price=float(output["stck_prpr"]),
            bid=None,
            ask=None,
            volume=float(output["acml_vol"]),
            exchange_ts=now,
            received_ts=now,
        )

    async def get_daily_prices(
        self, symbol: str, start_date: str, end_date: str, adjusted: bool = True
    ) -> list[Candle]:
        """Daily OHLCV between `start_date`/`end_date` (`YYYYMMDD`, KIS's own
        date format for this endpoint), returned chronological (oldest
        first) - matching Upbit's `get_daily_candles()` convention in this
        codebase even though KIS's own raw response order isn't
        independently confirmed here (see module docstring); reversing an
        already-ascending response is a no-op, so this is the safe default
        either way, and callers should treat the very first
        `get_daily_prices()` result as an explicit thing to re-check once
        real credentials exist.
        """
        token = await self._auth.get_access_token()
        response = await self._client.get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            headers={
                "authorization": f"Bearer {token}",
                "appkey": self._auth.settings.kis_app_key,
                "appsecret": self._auth.settings.kis_app_secret,
                "tr_id": _TR_ID_DAILY_CHART_PRICE,
                "custtype": "P",
            },
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": start_date,
                "FID_INPUT_DATE_2": end_date,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0" if adjusted else "1",
            },
        )
        body = response.json()
        if response.status_code != 200 or body.get("rt_cd") != "0":
            raise KisApiError(
                f"KIS inquire-daily-itemchartprice failed for {symbol}: {response.status_code} {body}"
            )

        rows = body.get("output2", [])
        candles = [self._to_daily_candle(row, symbol) for row in rows if row.get("stck_bsop_date")]
        candles.sort(key=lambda c: c.open_time)
        return candles

    def _to_daily_candle(self, row: dict, symbol: str) -> Candle:
        trade_date = datetime.strptime(row["stck_bsop_date"], "%Y%m%d").replace(tzinfo=UTC)
        return Candle(
            symbol=symbol,
            interval="1d",
            open=float(row["stck_oprc"]),
            high=float(row["stck_hgpr"]),
            low=float(row["stck_lwpr"]),
            close=float(row["stck_clpr"]),
            volume=float(row["acml_vol"]),
            open_time=trade_date,
            close_time=trade_date + timedelta(days=1),
        )
