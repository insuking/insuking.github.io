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
names and request params were not independently verified when first
written (KIS's docs portal and `github.com/koreainvestment/open-trading-api`
were both unreachable from the sandbox that wrote them, and no credentials
were provisioned yet). A real run against real KIS servers (2026-09, once
credentials existed) got past auth and field parsing on the first two
symbols before tripping the rate limit below - the strongest evidence yet
that the field layout is in fact correct, though still not a full
multi-symbol confirmation.

**Rate limit** (confirmed by that same real run, not a guess like the
"add one once needed" note this docstring used to carry): KIS returns
HTTP 500 with `{"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당
거래건수를 초과하였습니다"}" ("per-second transaction count exceeded")
under unthrottled sequential calls. `DEFAULT_MAX_REQUESTS_PER_SECOND`
below is a conservative starting point, not a number confirmed as KIS's
actual limit (that would need a documented rate this project still
hasn't been able to fetch) - tune it down further if EGW00201 still
appears, or up once a real multi-day run shows headroom.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.models.domain import AssetType, Candle, Exchange, Market, Quote

_TR_ID_CURRENT_PRICE = "FHKST01010100"
_TR_ID_DAILY_CHART_PRICE = "FHKST03010100"

_RATE_LIMIT_MSG_CD = "EGW00201"
DEFAULT_MAX_REQUESTS_PER_SECOND = 2.0
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 1.0
_MAX_RATE_LIMIT_RETRIES = 3

# get_index_daily_prices(): NOT independently verified (see that method's
# docstring) - "U" (지수) vs "J" (주식) for FID_COND_MRKT_DIV_CODE, and
# these index codes, are the commonly-documented convention across public
# KIS client libraries, not a payload this project has confirmed.
_INDEX_MARKET_DIV_CODE = "U"
KOSPI_INDEX_CODE = "0001"
KOSDAQ_INDEX_CODE = "1001"


class KisRestClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        auth: KisAuth,
        max_requests_per_second: float = DEFAULT_MAX_REQUESTS_PER_SECOND,
        rate_limit_backoff_seconds: float = DEFAULT_RATE_LIMIT_BACKOFF_SECONDS,
    ) -> None:
        self._client = client
        self._auth = auth
        self._min_request_interval = 1.0 / max_requests_per_second
        self._rate_limit_backoff_seconds = rate_limit_backoff_seconds
        self._throttle_lock = asyncio.Lock()
        self._next_allowed_at = 0.0

    async def get_quote(self, symbol: str, market: Market = Market.KOSPI) -> Quote:
        body = await self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            _TR_ID_CURRENT_PRICE,
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
        )
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
        codebase; a real run confirmed KIS also returns most-recent-first
        for this endpoint, so the sort below is doing real work, not a
        no-op.
        """
        body = await self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            _TR_ID_DAILY_CHART_PRICE,
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": start_date,
                "FID_INPUT_DATE_2": end_date,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0" if adjusted else "1",
            },
        )
        rows = body.get("output2", [])
        candles = [self._to_daily_candle(row, symbol) for row in rows if row.get("stck_bsop_date")]
        candles.sort(key=lambda c: c.open_time)
        return candles

    async def get_index_daily_prices(self, index_code: str, start_date: str, end_date: str) -> list[Candle]:
        """Daily KOSPI/KOSDAQ index candles via the same
        inquire-daily-itemchartprice endpoint `get_daily_prices()` uses for
        stocks, but with `FID_COND_MRKT_DIV_CODE="U"` (지수) instead of "J"
        (주식) - this is the piece `app/stock_radar/scan.py` has been using
        a flat placeholder benchmark in place of. NOT independently
        verified (KIS's docs and the response field names an index row
        actually uses could differ from a stock row's `stck_*` fields
        assumed here) - the first real call is the verification; if it
        raises `KeyError`/`KisApiError`, that's real signal about what to
        fix, not a bug to route around silently.
        """
        body = await self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            _TR_ID_DAILY_CHART_PRICE,
            {
                "FID_COND_MRKT_DIV_CODE": _INDEX_MARKET_DIV_CODE,
                "FID_INPUT_ISCD": index_code,
                "FID_INPUT_DATE_1": start_date,
                "FID_INPUT_DATE_2": end_date,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "0",
            },
        )
        rows = body.get("output2", [])
        candles = [self._to_daily_candle(row, index_code) for row in rows if row.get("stck_bsop_date")]
        candles.sort(key=lambda c: c.open_time)
        return candles

    async def _throttle(self) -> None:
        """Pace outgoing requests to at most `max_requests_per_second`,
        regardless of how many callers are dispatching concurrently - same
        shape as `UpbitRestClient._throttle()`, now grounded in KIS's own
        confirmed EGW00201 rate-limit response rather than Upbit's 429."""
        async with self._throttle_lock:
            now = asyncio.get_event_loop().time()
            wait = self._next_allowed_at - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = self._next_allowed_at
            self._next_allowed_at = max(now, self._next_allowed_at) + self._min_request_interval

    async def _get(self, path: str, tr_id: str, params: dict[str, str]) -> dict:
        response: httpx.Response | None = None
        body: dict = {}
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            await self._throttle()
            token = await self._auth.get_access_token()
            response = await self._client.get(
                path,
                headers={
                    "authorization": f"Bearer {token}",
                    "appkey": self._auth.settings.kis_app_key,
                    "appsecret": self._auth.settings.kis_app_secret,
                    "tr_id": tr_id,
                    "custtype": "P",
                },
                params=params,
            )
            try:
                body = response.json()
            except ValueError:
                body = {}
            if body.get("msg_cd") == _RATE_LIMIT_MSG_CD and attempt < _MAX_RATE_LIMIT_RETRIES:
                await asyncio.sleep(self._rate_limit_backoff_seconds * (attempt + 1))
                continue
            break
        assert response is not None  # loop always runs at least once

        if response.status_code != 200 or body.get("rt_cd") != "0":
            raise KisApiError(f"KIS {tr_id} failed: {response.status_code} {body}")
        return body

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
