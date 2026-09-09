"""Unit tests for the KIS REST client (mocked transport, see test_kis_auth.py note)."""

from datetime import timedelta

import httpx
import pytest

from app.core.config import Settings
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.rest_client import KisRestClient
from app.models.domain import AssetType, Exchange, Market

pytestmark = pytest.mark.P3


def _settings() -> Settings:
    return Settings(kis_app_key="test-key", kis_app_secret="test-secret")  # type: ignore[call-arg]


def _mock_client(
    auth_body: dict, quote_body: dict, requests: list[httpx.Request] | None = None
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json=auth_body)
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-price":
            assert request.headers["tr_id"] == "FHKST01010100"
            assert request.headers["authorization"] == "Bearer test-token"
            return httpx.Response(200, json=quote_body)
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")


@pytest.mark.asyncio
async def test_get_quote_parses_response_into_domain_model() -> None:
    requests: list[httpx.Request] = []
    client = _mock_client(
        auth_body={"access_token": "test-token", "expires_in": 86400},
        quote_body={
            "rt_cd": "0",
            "msg1": "정상처리 되었습니다.",
            "output": {"stck_prpr": "71000", "acml_vol": "12345678"},
        },
        requests=requests,
    )
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()))

    quote = await rest.get_quote("005930", market=Market.KOSPI)

    assert quote.symbol == "005930"
    assert quote.asset_type == AssetType.STOCK
    assert quote.exchange == Exchange.KRX
    assert quote.market == Market.KOSPI
    assert quote.price == 71000.0
    assert quote.volume == 12345678.0
    assert quote.exchange_ts == quote.received_ts

    quote_request = next(r for r in requests if "inquire-price" in str(r.url))
    assert quote_request.url.params["FID_INPUT_ISCD"] == "005930"


@pytest.mark.asyncio
async def test_get_quote_raises_on_non_zero_rt_cd() -> None:
    client = _mock_client(
        auth_body={"access_token": "test-token", "expires_in": 86400},
        quote_body={"rt_cd": "1", "msg1": "종목코드 오류", "output": {}},
    )
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()))

    with pytest.raises(KisApiError):
        await rest.get_quote("BADCODE")


@pytest.mark.asyncio
async def test_get_quote_retries_a_real_rate_limit_response_and_succeeds() -> None:
    """A real docker-compose run against real KIS servers tripped exactly
    this (EGW00201, '초당 거래건수를 초과하였습니다') on the third
    sequential get_daily_prices() call with nothing pacing requests - see
    rest_client.py's module docstring. The retry must not surface it as a
    hard failure when a later attempt succeeds."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        calls += 1
        if calls < 3:
            return httpx.Response(
                500, json={"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과하였습니다."}
            )
        return httpx.Response(200, json={"rt_cd": "0", "output": {"stck_prpr": "71000", "acml_vol": "100"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()), rate_limit_backoff_seconds=0.01)

    quote = await rest.get_quote("005930")

    assert quote.price == 71000.0
    assert calls == 3


@pytest.mark.asyncio
async def test_get_quote_raises_after_exhausting_rate_limit_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        return httpx.Response(500, json={"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과하였습니다."})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()), rate_limit_backoff_seconds=0.01)

    with pytest.raises(KisApiError):
        await rest.get_quote("005930")


@pytest.mark.asyncio
async def test_throttle_paces_concurrent_requests_under_the_configured_rate() -> None:
    import asyncio
    import time

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        return httpx.Response(200, json={"rt_cd": "0", "output": {"stck_prpr": "1", "acml_vol": "1"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()), max_requests_per_second=20.0)

    start = time.monotonic()
    await asyncio.gather(*(rest.get_quote("005930") for _ in range(5)))
    elapsed = time.monotonic() - start

    # 5 requests at 20/sec must take at least 4 intervals (0.2s) - a bug that
    # skipped throttling for concurrent callers would finish near-instantly.
    assert elapsed >= 0.19


def _mock_daily_client(auth_body: dict, daily_body: dict, requests: list[httpx.Request] | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json=auth_body)
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice":
            assert request.headers["tr_id"] == "FHKST03010100"
            return httpx.Response(200, json=daily_body)
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")


@pytest.mark.asyncio
async def test_get_daily_prices_parses_and_sorts_into_chronological_order() -> None:
    requests: list[httpx.Request] = []
    client = _mock_daily_client(
        auth_body={"access_token": "test-token", "expires_in": 86400},
        daily_body={
            "rt_cd": "0",
            "msg1": "정상처리 되었습니다.",
            "output1": {},
            # KIS convention (unverified, see rest_client.py docstring): most-recent-first.
            "output2": [
                {
                    "stck_bsop_date": "20260107",
                    "stck_oprc": "72000",
                    "stck_hgpr": "73000",
                    "stck_lwpr": "71500",
                    "stck_clpr": "72500",
                    "acml_vol": "1200000",
                },
                {
                    "stck_bsop_date": "20260106",
                    "stck_oprc": "70500",
                    "stck_hgpr": "71800",
                    "stck_lwpr": "70000",
                    "stck_clpr": "71000",
                    "acml_vol": "1000000",
                },
            ],
        },
        requests=requests,
    )
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()))

    candles = await rest.get_daily_prices("005930", "20260106", "20260107")

    assert [c.close for c in candles] == [71000.0, 72500.0]  # oldest first
    assert candles[0].open_time < candles[1].open_time
    assert candles[-1].close_time - candles[-1].open_time == timedelta(days=1)

    daily_request = next(r for r in requests if "inquire-daily-itemchartprice" in str(r.url))
    assert daily_request.url.params["FID_INPUT_ISCD"] == "005930"
    assert daily_request.url.params["FID_INPUT_DATE_1"] == "20260106"
    assert daily_request.url.params["FID_INPUT_DATE_2"] == "20260107"


@pytest.mark.asyncio
async def test_get_daily_prices_raises_on_non_zero_rt_cd() -> None:
    client = _mock_daily_client(
        auth_body={"access_token": "test-token", "expires_in": 86400},
        daily_body={"rt_cd": "1", "msg1": "조회 실패", "output1": {}, "output2": []},
    )
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()))

    with pytest.raises(KisApiError):
        await rest.get_daily_prices("BADCODE", "20260101", "20260107")


@pytest.mark.asyncio
async def test_get_daily_prices_skips_rows_missing_a_trade_date() -> None:
    client = _mock_daily_client(
        auth_body={"access_token": "test-token", "expires_in": 86400},
        daily_body={
            "rt_cd": "0",
            "output1": {},
            "output2": [
                {"stck_bsop_date": ""},
                {
                    "stck_bsop_date": "20260107",
                    "stck_oprc": "72000",
                    "stck_hgpr": "73000",
                    "stck_lwpr": "71500",
                    "stck_clpr": "72500",
                    "acml_vol": "1200000",
                },
            ],
        },
    )
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()))

    candles = await rest.get_daily_prices("005930", "20260101", "20260107")

    assert len(candles) == 1


@pytest.mark.asyncio
async def test_get_daily_prices_with_name_returns_the_korean_stock_name_from_output1() -> None:
    client = _mock_daily_client(
        auth_body={"access_token": "test-token", "expires_in": 86400},
        daily_body={
            "rt_cd": "0",
            "output1": {"hts_kor_isnm": "삼성전자"},
            "output2": [
                {
                    "stck_bsop_date": "20260107",
                    "stck_oprc": "72000",
                    "stck_hgpr": "73000",
                    "stck_lwpr": "71500",
                    "stck_clpr": "72500",
                    "acml_vol": "1200000",
                },
            ],
        },
    )
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()))

    candles, name = await rest.get_daily_prices_with_name("005930", "20260101", "20260107")

    assert len(candles) == 1
    assert name == "삼성전자"


@pytest.mark.asyncio
async def test_get_daily_prices_with_name_returns_none_when_output1_has_no_name() -> None:
    client = _mock_daily_client(
        auth_body={"access_token": "test-token", "expires_in": 86400},
        daily_body={"rt_cd": "0", "output1": {}, "output2": []},
    )
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()))

    _candles, name = await rest.get_daily_prices_with_name("005930", "20260101", "20260107")

    assert name is None


@pytest.mark.asyncio
async def test_get_index_daily_prices_uses_the_dedicated_index_endpoint() -> None:
    """A real docker-compose run against real KIS servers proved indices
    are NOT `get_daily_prices()`'s endpoint with a different market-division
    code - KIS rejected that with `{"rt_cd": "2", "msg_cd": "OPSQ2001",
    "msg1": "ERROR INVALID FID_COND_MRKT_DIV_CODE"}`. They're a separate
    endpoint, `inquire-daily-indexchartprice`, whose rows use `bstp_nmix_*`
    field names instead of a stock row's `stck_*` fields - see
    rest_client.py's module docstring."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice":
            assert request.headers["tr_id"] == "FHKUP03500100"
            return httpx.Response(
                200,
                json={
                    "rt_cd": "0",
                    "output1": {},
                    "output2": [
                        {
                            "stck_bsop_date": "20260107",
                            "bstp_nmix_oprc": "2500",
                            "bstp_nmix_hgpr": "2520",
                            "bstp_nmix_lwpr": "2490",
                            "bstp_nmix_prpr": "2510",
                            "acml_vol": "500000000",
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()))

    candles = await rest.get_index_daily_prices("0001", "20260101", "20260107")

    assert len(candles) == 1
    assert candles[0].close == 2510.0
    assert candles[0].open == 2500.0

    index_request = next(r for r in requests if "inquire-daily-indexchartprice" in str(r.url))
    assert index_request.url.params["FID_COND_MRKT_DIV_CODE"] == "U"
    assert index_request.url.params["FID_INPUT_ISCD"] == "0001"


@pytest.mark.asyncio
async def test_get_investor_trend_parses_foreign_and_institution_net_buy_and_sorts_chronologically() -> None:
    """`inquire-investor` (P25) returns a single flat `output` array (not
    output1/output2 like the daily-price endpoints) - confirmed against
    KIS's public sample repo, see rest_client.py's module docstring."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-investor":
            assert request.headers["tr_id"] == "FHKST01010900"
            return httpx.Response(
                200,
                json={
                    "rt_cd": "0",
                    # KIS convention (other daily endpoints return most-recent-first): assume the same here.
                    "output": [
                        {"stck_bsop_date": "20260107", "frgn_ntby_qty": "1000", "orgn_ntby_qty": "-500"},
                        {"stck_bsop_date": "20260106", "frgn_ntby_qty": "-200", "orgn_ntby_qty": "300"},
                    ],
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()))

    bars = await rest.get_investor_trend("005930")

    assert len(bars) == 2
    assert bars[0].foreign_net_qty == -200.0  # oldest (20260106) first
    assert bars[0].institution_net_qty == 300.0
    assert bars[1].foreign_net_qty == 1000.0  # newest (20260107) last
    assert bars[1].institution_net_qty == -500.0

    investor_request = next(r for r in requests if "inquire-investor" in str(r.url))
    assert investor_request.url.params["FID_COND_MRKT_DIV_CODE"] == "J"
    assert investor_request.url.params["FID_INPUT_ISCD"] == "005930"


@pytest.mark.asyncio
async def test_get_investor_trend_raises_on_non_zero_rt_cd() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/tokenP":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 86400})
        if request.url.path == "/uapi/domestic-stock/v1/quotations/inquire-investor":
            return httpx.Response(200, json={"rt_cd": "1", "msg1": "조회 실패", "output": []})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.kis.test")
    rest = KisRestClient(client, KisAuth(client=client, settings=_settings()))

    with pytest.raises(KisApiError):
        await rest.get_investor_trend("BADCODE")
