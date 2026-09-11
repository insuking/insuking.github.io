"""Unit tests for KisWebSocketClient using a fake connection (no real network).

`websockets.connect` isn't touched here - `connect=` is injected with a fake
async context manager that yields canned messages, per the master spec's
"mocks only in unit tests" rule.
"""

import asyncio
import json
from typing import Self

import pytest

from app.events import Stream
from app.integrations.kis.fields import H0STCNT0_FIELDS
from app.integrations.kis.ws_client import KisWebSocketClient

pytestmark = pytest.mark.P3


class FakeConnection:
    """One simulated socket lifetime: yields `messages`, then closes."""

    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for m in self.messages:
            yield m

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class FakeAuth:
    async def get_ws_approval_key(self) -> str:
        return "fake-approval-key"


def _trade_message(symbol: str) -> str:
    values = {name: "0" for name in H0STCNT0_FIELDS}
    values.update({"MKSC_SHRN_ISCD": symbol, "STCK_CNTG_HOUR": "093015", "STCK_PRPR": "71000", "CNTG_VOL": "1"})
    body = "^".join(values[name] for name in H0STCNT0_FIELDS)
    return f"0|H0STCNT0|1|{body}"


@pytest.mark.asyncio
async def test_subscribe_before_connect_is_sent_on_first_connect() -> None:
    connections: list[FakeConnection] = [FakeConnection([])]

    def fake_connect(_url: str) -> FakeConnection:
        return connections.pop(0)

    published: list[tuple[Stream, dict]] = []

    async def fake_publish(stream: Stream, payload: dict) -> str:
        published.append((stream, payload))
        return "0-1"

    client = KisWebSocketClient(
        auth=FakeAuth(), connect=fake_connect, publish_fn=fake_publish
    )
    await client.subscribe("H0STCNT0", "005930")

    run_task = asyncio.create_task(client.run())
    await asyncio.sleep(0.05)
    await client.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert client.subscriptions == frozenset({("H0STCNT0", "005930")})


@pytest.mark.asyncio
async def test_realtime_trade_message_is_published() -> None:
    conn = FakeConnection([_trade_message("005930")])

    def fake_connect(_url: str) -> FakeConnection:
        return conn

    published: list[tuple[Stream, dict]] = []

    async def fake_publish(stream: Stream, payload: dict) -> str:
        published.append((stream, payload))
        return "0-1"

    client = KisWebSocketClient(
        auth=FakeAuth(), connect=fake_connect, publish_fn=fake_publish
    )
    await client.subscribe("H0STCNT0", "005930")

    run_task = asyncio.create_task(client.run())
    await asyncio.sleep(0.1)
    await client.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert len(published) == 1
    stream, payload = published[0]
    assert stream == Stream.MARKET_TRADE
    assert payload["symbol"] == "005930"


@pytest.mark.asyncio
async def test_pingpong_is_echoed_back() -> None:
    ping = json.dumps({"header": {"tr_id": "PINGPONG"}})
    conn = FakeConnection([ping])

    def fake_connect(_url: str) -> FakeConnection:
        return conn

    async def fake_publish(stream: Stream, payload: dict) -> str:
        return "0-1"

    client = KisWebSocketClient(
        auth=FakeAuth(), connect=fake_connect, publish_fn=fake_publish
    )
    run_task = asyncio.create_task(client.run())
    await asyncio.sleep(0.05)
    await client.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert ping in conn.sent


@pytest.mark.asyncio
async def test_reconnect_replays_all_subscriptions() -> None:
    """Regression coverage for P3's 'subscription restore' requirement."""
    first_conn = FakeConnection([])  # drops immediately (no messages, then closes)
    second_conn = FakeConnection([])
    connections = [first_conn, second_conn]

    def fake_connect(_url: str) -> FakeConnection:
        return connections.pop(0)

    async def fake_publish(stream: Stream, payload: dict) -> str:
        return "0-1"

    client = KisWebSocketClient(
        auth=FakeAuth(),
        connect=fake_connect,
        publish_fn=fake_publish,
    )
    await client.subscribe("H0STCNT0", "005930")
    await client.subscribe("H0STASP0", "000660")

    run_task = asyncio.create_task(client.run())
    # A connection with zero messages ends immediately; run() resets backoff
    # to 1s on every successful connect before reconnecting, so this needs
    # to outlast that one full backoff interval to observe the reconnect.
    await asyncio.sleep(1.3)
    await client.stop()
    await asyncio.wait_for(run_task, timeout=2)

    expected = [
        json.dumps(
            {
                "header": {
                    "approval_key": "fake-approval-key",
                    "custtype": "P",
                    "tr_type": "1",
                    "content-type": "utf-8",
                },
                "body": {"input": {"tr_id": tr_id, "tr_key": symbol}},
            }
        )
        for tr_id, symbol in sorted(client.subscriptions)
    ]
    assert first_conn.sent == expected
    assert second_conn.sent == expected  # replayed identically after reconnect
