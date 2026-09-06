"""KIS REST client (P3): domestic stock current-price snapshot.

Only the one endpoint P3 needs is implemented (현재가 조회,
`/uapi/domestic-stock/v1/quotations/inquire-price`) - order placement is a
later phase (P15) and must not exist yet per the master spec's "implement
only the active phase" rule.

Note on timestamps: this snapshot endpoint does not return an exchange-side
transaction time, only current values - unlike the WebSocket tick feed
(`ws_client.py`), which carries a real `stck_cntg_hour` per trade. So
`exchange_ts` here is set equal to `received_ts` rather than fabricated;
callers needing true exchange-vs-received latency should use the WS stream.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.models.domain import AssetType, Exchange, Market, Quote

_TR_ID_CURRENT_PRICE = "FHKST01010100"


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
