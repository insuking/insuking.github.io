"""P7 acceptance: real connection to Upbit's public WS/REST, no mocking.

Upbit's public market data needs no API key, so unlike test_kis_integration.py
/ test_toss_integration.py this can't skip on "not configured". What it
skips on instead is a real network-level failure establishing the
connection - this sandbox's egress policy blocks api.upbit.com outright
(confirmed with a direct `websockets.connect` attempt, which the proxy
rejected with an HTTP 403; see docs/UPBIT_NOTES.md). Only the connection
*attempt* is allowed to turn into a skip - anything that goes wrong after a
real connection is established (bad frame, parsing error, unexpected
schema) fails the test for real, since that would be an actual bug once
network access exists.
"""

import json

import httpx
import pytest
import websockets

from app.core.config import get_settings
from app.integrations.upbit.rest_client import UpbitRestClient

pytestmark = pytest.mark.P7


def _skip_if_unreachable(exc: Exception) -> None:
    pytest.skip(
        f"could not reach Upbit from this sandbox (network egress blocked): "
        f"{type(exc).__name__}: {exc}"
    )


@pytest.mark.asyncio
async def test_real_upbit_rest_ticker() -> None:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.upbit_rest_base_url, timeout=10.0) as client:
        try:
            response = await client.get("/v1/ticker", params={"markets": "KRW-BTC"})
        except httpx.HTTPError as exc:
            _skip_if_unreachable(exc)
            return

        assert response.status_code == 200
        rest = UpbitRestClient(client)
        price = await rest.get_ticker_price("KRW-BTC")
        assert price > 0


@pytest.mark.asyncio
async def test_real_upbit_websocket_ticker_message() -> None:
    settings = get_settings()
    try:
        websocket_cm = websockets.connect(settings.upbit_ws_url)
        ws = await websocket_cm.__aenter__()
    except Exception as exc:  # noqa: BLE001 - connection-establishment only, see module docstring
        _skip_if_unreachable(exc)
        return

    try:
        await ws.send(
            json.dumps(
                [
                    {"ticket": "p7-integration-test"},
                    {"type": "ticker", "codes": ["KRW-BTC"]},
                    {"format": "DEFAULT"},
                ]
            )
        )
        raw = await ws.recv()
        message = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)

        assert message["type"] == "ticker"
        assert message["code"] == "KRW-BTC"
        assert message["trade_price"] > 0
    finally:
        await websocket_cm.__aexit__(None, None, None)
