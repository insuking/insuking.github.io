"""Unit tests for UpbitWebSocketClient using a fake connection (no real network)."""

import asyncio
import json
from typing import Self

import pytest

from app.events import Stream
from app.integrations.upbit.ws_client import UpbitWebSocketClient

pytestmark = pytest.mark.P7


class FakeConnection:
    """One simulated socket lifetime: yields `messages`, then idles until closed."""

    def __init__(self, messages: list[str] | None = None) -> None:
        self.messages = messages or []
        self.sent: list[str] = []
        self._closed = asyncio.Event()

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self._closed.set()

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for m in self.messages:
            yield m
        # After the scripted messages, idle until close() is called instead
        # of ending the iterator immediately - lets staleness tests hold a
        # connection open without messages, like a real silent socket would.
        await self._closed.wait()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None


def _trade_message(symbol: str, price: float = 71000000.0) -> str:
    return json.dumps(
        {
            "type": "trade",
            "code": symbol,
            "trade_price": price,
            "trade_volume": 0.01,
            "ask_bid": "BID",
            "trade_timestamp": 1735000000000,
        }
    )


@pytest.mark.asyncio
async def test_subscribe_frame_has_ticket_type_codes_and_format() -> None:
    conn = FakeConnection()

    def fake_connect(_url: str) -> FakeConnection:
        return conn

    async def fake_publish(stream: Stream, payload: dict) -> str:
        return "0-1"

    client = UpbitWebSocketClient(connect=fake_connect, publish_fn=fake_publish)
    await client.subscribe("trade", ["KRW-BTC"])

    run_task = asyncio.create_task(client.run())
    await asyncio.sleep(0.05)
    await client.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert len(conn.sent) == 1
    frame = json.loads(conn.sent[0])
    assert "ticket" in frame[0]
    assert frame[1] == {"type": "trade", "codes": ["KRW-BTC"]}
    assert frame[-1] == {"format": "DEFAULT"}


@pytest.mark.asyncio
async def test_trade_message_is_published_to_market_trade_stream() -> None:
    conn = FakeConnection([_trade_message("KRW-BTC")])

    def fake_connect(_url: str) -> FakeConnection:
        return conn

    published = []

    async def fake_publish(stream: Stream, payload: dict) -> str:
        published.append((stream, payload))
        return "0-1"

    client = UpbitWebSocketClient(connect=fake_connect, publish_fn=fake_publish)
    await client.subscribe("trade", ["KRW-BTC"])

    run_task = asyncio.create_task(client.run())
    await asyncio.sleep(0.1)
    await client.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert len(published) == 1
    stream, payload = published[0]
    assert stream == Stream.MARKET_TRADE
    assert payload["symbol"] == "KRW-BTC"


@pytest.mark.asyncio
async def test_orderbook_and_ticker_messages_route_to_their_own_streams() -> None:
    orderbook_msg = json.dumps(
        {
            "type": "orderbook",
            "code": "KRW-BTC",
            "timestamp": 1735000000000,
            "total_ask_size": 1,
            "total_bid_size": 1,
            "orderbook_units": [{"ask_price": 101, "bid_price": 100, "ask_size": 1, "bid_size": 1}],
        }
    )
    ticker_msg = json.dumps(
        {
            "type": "ticker",
            "code": "KRW-BTC",
            "trade_price": 100.0,
            "acc_trade_volume_24h": 10.0,
            "trade_timestamp": 1735000000000,
        }
    )
    conn = FakeConnection([orderbook_msg, ticker_msg])

    def fake_connect(_url: str) -> FakeConnection:
        return conn

    published = []

    async def fake_publish(stream: Stream, payload: dict) -> str:
        published.append(stream)
        return "0-1"

    client = UpbitWebSocketClient(connect=fake_connect, publish_fn=fake_publish)
    run_task = asyncio.create_task(client.run())
    await asyncio.sleep(0.1)
    await client.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert published == [Stream.MARKET_ORDERBOOK, Stream.MARKET_TICKER]


@pytest.mark.asyncio
async def test_reconnect_replays_all_subscriptions() -> None:
    """Regression coverage for P7's 'subscription restore' requirement."""
    first_conn = FakeConnection()
    second_conn = FakeConnection()
    connections = [first_conn, second_conn]

    def fake_connect(_url: str) -> FakeConnection:
        return connections.pop(0)

    async def fake_publish(stream: Stream, payload: dict) -> str:
        return "0-1"

    client = UpbitWebSocketClient(connect=fake_connect, publish_fn=fake_publish)
    await client.subscribe("trade", ["KRW-BTC"])
    await client.subscribe("orderbook", ["KRW-ETH"])

    run_task = asyncio.create_task(client.run())
    await asyncio.sleep(0.05)
    # Simulate the first connection dying (server closed it) rather than
    # our own stop() - that's what a real reconnect looks like.
    await first_conn.close()
    await asyncio.sleep(1.3)  # past the 1s initial backoff before reconnecting
    await client.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert len(first_conn.sent) == 1
    assert len(second_conn.sent) == 1
    # The `ticket` field is a fresh random id per frame by design - compare
    # everything else, which is what "replays the same subscriptions" means.
    first_frame = json.loads(first_conn.sent[0])
    second_frame = json.loads(second_conn.sent[0])
    assert first_frame[1:] == second_frame[1:]


@pytest.mark.asyncio
async def test_staleness_watchdog_forces_reconnect_when_silent() -> None:
    first_conn = FakeConnection()
    second_conn = FakeConnection()
    connections = [first_conn, second_conn]

    def fake_connect(_url: str) -> FakeConnection:
        return connections.pop(0)

    async def fake_publish(stream: Stream, payload: dict) -> str:
        return "0-1"

    client = UpbitWebSocketClient(
        connect=fake_connect,
        publish_fn=fake_publish,
        stale_timeout_seconds=0.1,
    )
    await client.subscribe("trade", ["KRW-BTC"])

    run_task = asyncio.create_task(client.run())
    # No messages at all on first_conn - the watchdog (polling every 5s by
    # design, but we only need it to have fired once) should close it well
    # within this window and force a reconnect onto second_conn.
    await asyncio.sleep(6.5)
    await client.stop()
    await asyncio.wait_for(run_task, timeout=2)

    assert len(second_conn.sent) == 1


@pytest.mark.asyncio
async def test_processing_many_messages_does_not_grow_client_state() -> None:
    """P7 acceptance: '24h-compatible memory behavior' - no unbounded buffers."""
    published_count = 0

    async def fake_publish(stream: Stream, payload: dict) -> str:
        nonlocal published_count
        published_count += 1
        return "0-1"

    client = UpbitWebSocketClient(publish_fn=fake_publish)
    await client.subscribe("trade", ["KRW-BTC"])

    def collection_sizes() -> dict[str, int | None]:
        return {
            name: (len(value) if isinstance(value, (list, dict, set, frozenset, tuple)) else None)
            for name, value in vars(client).items()
        }

    before = collection_sizes()

    for i in range(5000):
        await client._handle_message(_trade_message("KRW-BTC", price=71000000.0 + i))

    after = collection_sizes()

    assert published_count == 5000
    assert before == after
