"""P9: Upbit KRW universe fetch + TOP200/TOP30/TOP5 funnel reuse."""

import httpx
import pytest

from app.integrations.upbit.rest_client import UpbitRestClient
from app.radar.ranking import rank_candidates

pytestmark = pytest.mark.P9


@pytest.mark.asyncio
async def test_get_krw_market_universe_filters_to_krw_prefix() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/market/all"
        assert request.url.params["isDetails"] == "false"
        return httpx.Response(
            200,
            json=[
                {"market": "KRW-BTC", "korean_name": "비트코인"},
                {"market": "KRW-ETH", "korean_name": "이더리움"},
                {"market": "BTC-ETH", "korean_name": "이더리움"},  # non-KRW market, must be dropped
                {"market": "USDT-BTC", "korean_name": "비트코인"},
            ],
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.upbit.test")
    rest = UpbitRestClient(client)

    universe = await rest.get_krw_market_universe()

    assert universe == ["KRW-BTC", "KRW-ETH"]


def test_top200_30_5_funnel_reuses_p4_ranking_for_a_crypto_universe() -> None:
    """No crypto-specific ranking code exists (or should exist) - P4's
    generic (symbol, score) funnel is the whole implementation here too.
    """
    universe = [(f"KRW-COIN{i:04d}", float(i)) for i in range(250)]

    funnel = rank_candidates(universe)

    assert len(funnel.top200) == 200
    assert len(funnel.top30) == 30
    assert len(funnel.top5) == 5
    assert funnel.top5[0].symbol == "KRW-COIN0249"
    assert funnel.top5[0].score == 249.0
