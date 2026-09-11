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

`get_index_daily_prices()` originally guessed it could reuse
`inquire-daily-itemchartprice` with `FID_COND_MRKT_DIV_CODE="U"`. A real
run proved that guess wrong: KIS returned `200 {"rt_cd": "2", "msg_cd":
"OPSQ2001", "msg1": "ERROR INVALID FID_COND_MRKT_DIV_CODE"}` - that
endpoint only accepts stock/ETF/ETN division codes. Once outbound web
access was available, `github.com/koreainvestment/open-trading-api`'s own
sample (`examples_llm/domestic_stock/inquire_daily_indexchartprice/`)
confirmed indices are a **separate endpoint**,
`inquire-daily-indexchartprice` (tr_id `FHKUP03500100`), whose daily rows
use `bstp_nmix_*` field names (업종지수, "sector/composite index") instead
of a stock row's `stck_*` fields - confirmed correct by a real
docker-compose run (2026-09).

`get_investor_trend()` (P25) is `inquire-investor` (tr_id
`FHKST01010900`) - daily foreign (외국인) and institutional (기관) net-buy
share counts per symbol, confirmed against KIS's public sample repo
(`examples_llm/domestic_stock/inquire_investor/`) but not yet against a
live response from this project's own credentials. Unlike the daily-price
endpoints, it takes no date range (KIS returns a fixed recent window
under a single `output` array, not `output1`/`output2`) and returns
program-trading (프로그램) flow nowhere in its fields - see
`app/stock_radar/investor_flow.py` for why that's a documented, not
silent, gap.

`get_account_balance()` (P45) is 주식잔고조회
(`/uapi/domestic-stock/v1/trading/inquire-balance`, tr_id `TTTC8434R`
real / `VTTC8434R` paper - same real/paper split as `orders.py`'s
`_TR_ID_BUY`/etc, confirmed from the same public sample repo's
`examples_llm/domestic_stock/inquire_balance/inquire_balance.py` plus its
companion `chk_inquire_balance.py`, which gave the full `output1`
(per-holding rows)/`output2` (account-summary row) column-name mapping
used below. Only `output2`'s summary row is read here - `dnca_tot_amt`
(예수금총금액/cash), `scts_evlu_amt`(유가평가금액/securities value),
`tot_evlu_amt`(총평가금액/total assets = cash + securities at current
price) - this project has no use yet for `output1`'s per-holding detail
since `app/api/dashboard.py`'s own `/positions/live-prices` (P42) already
gets per-symbol current price straight from `get_quote()`. Like
`get_daily_prices()`/`get_investor_trend()`, not yet confirmed against a
live response from this project's own credentials.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.models.domain import AssetType, Candle, Exchange, Market, Quote
from app.stock_radar.investor_flow import InvestorFlowBar

_TR_ID_CURRENT_PRICE = "FHKST01010100"
_TR_ID_DAILY_CHART_PRICE = "FHKST03010100"
_TR_ID_DAILY_INDEX_CHART_PRICE = "FHKUP03500100"
_TR_ID_INVESTOR_TREND = "FHKST01010900"
_TR_ID_BALANCE = {"real": "TTTC8434R", "paper": "VTTC8434R"}


@dataclass
class AccountBalance:
    cash: float
    securities_value: float
    total_value: float

_RATE_LIMIT_MSG_CD = "EGW00201"
DEFAULT_MAX_REQUESTS_PER_SECOND = 2.0
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 1.0
_MAX_RATE_LIMIT_RETRIES = 3

# get_index_daily_prices(): confirmed against KIS's own public sample repo
# (see module docstring) - not yet confirmed against a live response from
# this project's own credentials.
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
        candles, _name = await self.get_daily_prices_with_name(symbol, start_date, end_date, adjusted)
        return candles

    async def get_daily_prices_with_name(
        self, symbol: str, start_date: str, end_date: str, adjusted: bool = True
    ) -> tuple[list[Candle], str | None]:
        """Same request as `get_daily_prices()`, also returning the Korean
        stock name (`hts_kor_isnm`, confirmed against KIS's public sample
        repo) from `output1` - which `get_daily_prices()` fetches but
        discards. A separate method rather than changing
        `get_daily_prices()`'s return shape, so existing callers that only
        want candles don't have to unpack a tuple; callers that also want a
        display name (e.g. `scripts/scan_stocks.py`) get it for free,
        without a second rate-limited round trip.
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
        name = (body.get("output1") or {}).get("hts_kor_isnm") or None
        rows = body.get("output2", [])
        candles = [self._to_daily_candle(row, symbol) for row in rows if row.get("stck_bsop_date")]
        candles.sort(key=lambda c: c.open_time)
        return candles, name

    async def get_index_daily_prices(self, index_code: str, start_date: str, end_date: str) -> list[Candle]:
        """Daily KOSPI/KOSDAQ index candles - this is the piece
        `app/stock_radar/scan.py` has been using a flat placeholder
        benchmark in place of. A real run proved indices are NOT just
        `get_daily_prices()`'s endpoint with a different market-division
        code (KIS rejected that with `OPSQ2001 ERROR INVALID
        FID_COND_MRKT_DIV_CODE`) - they're a separate endpoint,
        `inquire-daily-indexchartprice`, confirmed via KIS's own public
        sample repo (see module docstring). Still not confirmed against a
        live response from this project's own credentials - if this raises
        `KeyError`/`KisApiError`, that's real signal about what to fix
        next, not a bug to route around silently.
        """
        body = await self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice",
            _TR_ID_DAILY_INDEX_CHART_PRICE,
            {
                "FID_COND_MRKT_DIV_CODE": _INDEX_MARKET_DIV_CODE,
                "FID_INPUT_ISCD": index_code,
                "FID_INPUT_DATE_1": start_date,
                "FID_INPUT_DATE_2": end_date,
                "FID_PERIOD_DIV_CODE": "D",
            },
        )
        rows = body.get("output2", [])
        candles = [self._to_daily_index_candle(row, index_code) for row in rows if row.get("stck_bsop_date")]
        candles.sort(key=lambda c: c.open_time)
        return candles

    async def get_investor_trend(self, symbol: str) -> list[InvestorFlowBar]:
        """Daily foreign/institutional net-buy share counts (P25) - see
        module docstring for the field/endpoint provenance. Chronological
        (oldest first), matching every other daily series in this class,
        though unlike them this endpoint takes no date-range params - KIS
        decides how much history to return.
        """
        body = await self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-investor",
            _TR_ID_INVESTOR_TREND,
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
        )
        rows = body.get("output", [])
        bars = [self._to_investor_flow_bar(row) for row in rows if row.get("stck_bsop_date")]
        bars.sort(key=lambda b: b.date)
        return bars

    async def get_account_balance(self, cano: str, acnt_prdt_cd: str, paper_trading: bool = True) -> AccountBalance:
        """Real cash/securities/total-asset value for the account
        (`cano`/`acnt_prdt_cd` - see `Settings.kis_cano`/`kis_acnt_prdt_cd`)
        - see module docstring for field provenance. `output2` is a
        one-row account summary (unlike `output1`'s per-holding list, not
        read here); an empty/missing row degrades to all-zero rather than
        raising, matching this endpoint's own "no holdings yet" case."""
        body = await self._get(
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            _TR_ID_BALANCE["paper" if paper_trading else "real"],
            {
                "CANO": cano,
                "ACNT_PRDT_CD": acnt_prdt_cd,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
        )
        summary_rows = body.get("output2") or [{}]
        row = summary_rows[0]
        return AccountBalance(
            cash=float(row.get("dnca_tot_amt") or 0),
            securities_value=float(row.get("scts_evlu_amt") or 0),
            total_value=float(row.get("tot_evlu_amt") or 0),
        )

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

    def _to_daily_index_candle(self, row: dict, index_code: str) -> Candle:
        """`inquire-daily-indexchartprice` rows use `bstp_nmix_*` (업종지수)
        field names, not a stock row's `stck_*` fields - confirmed against
        KIS's own public sample repo, see this module's docstring."""
        trade_date = datetime.strptime(row["stck_bsop_date"], "%Y%m%d").replace(tzinfo=UTC)
        return Candle(
            symbol=index_code,
            interval="1d",
            open=float(row["bstp_nmix_oprc"]),
            high=float(row["bstp_nmix_hgpr"]),
            low=float(row["bstp_nmix_lwpr"]),
            close=float(row["bstp_nmix_prpr"]),
            volume=float(row["acml_vol"]),
            open_time=trade_date,
            close_time=trade_date + timedelta(days=1),
        )

    def _to_investor_flow_bar(self, row: dict) -> InvestorFlowBar:
        """`inquire-investor` rows use `frgn_ntby_qty`/`orgn_ntby_qty`
        (외국인/기관 순매수 수량) - confirmed against KIS's public sample
        repo, see this module's docstring."""
        trade_date = datetime.strptime(row["stck_bsop_date"], "%Y%m%d").replace(tzinfo=UTC)
        return InvestorFlowBar(
            date=trade_date,
            foreign_net_qty=float(row["frgn_ntby_qty"]),
            institution_net_qty=float(row["orgn_ntby_qty"]),
        )
