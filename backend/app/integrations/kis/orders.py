"""KIS domestic-stock order placement/cancel (P29).

`inquire-price`/`inquire-daily-itemchartprice`/`inquire-investor`
(P3/P23/P25) are all read-only; this is the first KIS endpoint in this
project that can move real money, so its field layout was verified more
carefully than usual, cross-checked across three separate fetches of
`koreainvestment/open-trading-api`'s own sample code rather than a single
source:

- **Place** (`POST /uapi/domestic-stock/v1/trading/order-cash`):
  tr_id `TTTC0012U` (매수/buy) / `TTTC0011U` (매도/sell) for real trading,
  `VTTC0012U`/`VTTC0011U` for 모의투자 (paper) - confirmed from the sample
  repo's `order_cash.py` and cross-checked by an independent search hit
  giving the same four values. Body fields: `CANO` (8-digit account
  number), `ACNT_PRDT_CD` (2-digit account product code), `PDNO` (6-digit
  stock code), `ORD_DVSN` (order type - `"00"` confirmed as 지정가/limit
  from the sample's own real usage alongside a real `ORD_UNPR`; `"01"`
  for 시장가/market is the commonly-documented convention, not verified
  against a real market-order sample), `ORD_QTY` (quantity, as a string),
  `ORD_UNPR` (limit price, as a string - `"0"` for a market order),
  `EXCG_ID_DVSN_CD` (exchange routing - `"SOR"` here, matching the
  sample's own literal choice rather than substituting a different
  default).

- **Cancel/modify** (`POST /uapi/domestic-stock/v1/trading/order-rvsecncl`):
  tr_id `TTTC0013U` real / `VTTC0013U` paper (one tr_id handles both revise
  and cancel - `RVSE_CNCL_DVSN_CD` distinguishes them: `"02"`=cancel,
  `"01"`=revise, only cancel is implemented here). Needs the *original*
  order's `KRX_FWDG_ORD_ORGNO` (거래소코드, returned by the place call,
  not something this project generates) and `ORGN_ODNO` (original order
  number) alongside `QTY_ALL_ORD_YN` (`"Y"` = cancel the full remaining
  quantity, which is all this module supports - a partial cancel would
  need a real, non-zero `ORD_QTY` this project has no verified use for
  yet).

**Not implemented here**: reconciliation (`inquire-daily-ccld`, 일별주문
체결조회) - its response field names (fill quantity, fill price, status
code per row) were not confirmed against a real payload or a fully
detailed sample, unlike everything above. `KisExecutionProvider.
reconcile_order()` documents this gap rather than guessing at those
field names - guessing wrong there risks silently misreporting a real
order's fate, which is a worse failure mode than admitting "not built yet".

**Hashkey**: KIS's own docs describe a `POST /uapi/hashkey` step as
optional for order requests ("해쉬키 발급 (필수아님)" - confirmed via a
real KIS Developers wikidocs page, not just inferred), so it is
deliberately not sent here rather than adding an unverified extra
network call per order.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError

_TR_ID_BUY = {"real": "TTTC0012U", "paper": "VTTC0012U"}
_TR_ID_SELL = {"real": "TTTC0011U", "paper": "VTTC0011U"}
_TR_ID_CANCEL = {"real": "TTTC0013U", "paper": "VTTC0013U"}

ORDER_DIVISION_LIMIT = "00"
ORDER_DIVISION_MARKET = "01"
_EXCHANGE_ID_DIVISION = "SOR"
_CANCEL_DIVISION_CODE = "02"


class KisOrderClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        auth: KisAuth,
        cano: str,
        acnt_prdt_cd: str,
        paper_trading: bool = True,
    ) -> None:
        self._client = client
        self._auth = auth
        self._cano = cano
        self._acnt_prdt_cd = acnt_prdt_cd
        self._env = "paper" if paper_trading else "real"

    async def place_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: str,
        price: str | None = None,
        order_division: str = ORDER_DIVISION_LIMIT,
    ) -> dict[str, Any]:
        """`side`: `"BUY"` or `"SELL"`. `price`: required (a real limit
        price, as a string) for `ORDER_DIVISION_LIMIT`; omit (or pass
        `None`) for `ORDER_DIVISION_MARKET`, which sends `"0"` per KIS
        convention for a market order's price field.
        """
        if side == "BUY":
            tr_id = _TR_ID_BUY[self._env]
        elif side == "SELL":
            tr_id = _TR_ID_SELL[self._env]
        else:
            raise ValueError(f"side must be BUY or SELL, got {side!r}")

        body = {
            "CANO": self._cano,
            "ACNT_PRDT_CD": self._acnt_prdt_cd,
            "PDNO": symbol,
            "ORD_DVSN": order_division,
            "ORD_QTY": quantity,
            "ORD_UNPR": price if price is not None else "0",
            "EXCG_ID_DVSN_CD": _EXCHANGE_ID_DIVISION,
        }
        return await self._post("/uapi/domestic-stock/v1/trading/order-cash", tr_id, body)

    async def cancel_order(
        self,
        *,
        krx_fwdg_ord_orgno: str,
        original_order_no: str,
        symbol: str,
        order_division: str = ORDER_DIVISION_LIMIT,
    ) -> dict[str, Any]:
        """Cancels the full remaining quantity of an existing order.
        `krx_fwdg_ord_orgno`/`original_order_no` come from that order's own
        `place_order()` response (`KRX_FWDG_ORD_ORGNO`/`ODNO`) - never
        constructed locally.
        """
        tr_id = _TR_ID_CANCEL[self._env]
        body = {
            "CANO": self._cano,
            "ACNT_PRDT_CD": self._acnt_prdt_cd,
            "KRX_FWDG_ORD_ORGNO": krx_fwdg_ord_orgno,
            "ORGN_ODNO": original_order_no,
            "ORD_DVSN": order_division,
            "RVSE_CNCL_DVSN_CD": _CANCEL_DIVISION_CODE,
            "ORD_QTY": "0",
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",
            "EXCG_ID_DVSN_CD": _EXCHANGE_ID_DIVISION,
        }
        return await self._post("/uapi/domestic-stock/v1/trading/order-rvsecncl", tr_id, body)

    async def _post(self, path: str, tr_id: str, body: dict[str, str]) -> dict[str, Any]:
        token = await self._auth.get_access_token()
        response = await self._client.post(
            path,
            headers={
                "authorization": f"Bearer {token}",
                "appkey": self._auth.settings.kis_app_key,
                "appsecret": self._auth.settings.kis_app_secret,
                "tr_id": tr_id,
                "custtype": "P",
                "content-type": "application/json; charset=utf-8",
            },
            json=body,
        )
        try:
            parsed = response.json()
        except ValueError:
            parsed = {}

        if response.status_code != 200 or parsed.get("rt_cd") != "0":
            raise KisApiError(f"KIS {tr_id} failed: {response.status_code} {parsed}")
        return parsed
