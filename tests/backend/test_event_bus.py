"""P2 acceptance: 'event integration test' against a real Redis instance."""

import uuid

import pytest

from app.events import (
    Stream,
    ack,
    ensure_group,
    latest_id,
    publish,
    read_group,
    read_new,
    read_range,
)

pytestmark = pytest.mark.P2


@pytest.mark.asyncio
async def test_publish_then_read_range_round_trips_payload() -> None:
    """Regression note: this must scope the read to `start=entry_id`, not a
    bare `count`. This test's stream is shared across every run of this
    suite ever executed against this Redis instance, so a plain
    `read_range(stream, count=N)` reads the *oldest* N entries in the
    stream's entire history - on a stream old enough, that no longer
    includes anything just published, and this test starts failing for a
    reason that has nothing to do with a real bug (see the same class of
    issue fixed for `ensure_group` in app/events/bus.py).
    """
    stream = Stream.MARKET_TRADE
    payload = {"symbol": "KRW-XRP", "price": 4100.5, "quantity": 12.0, "nonce": str(uuid.uuid4())}

    entry_id = await publish(stream, payload)
    assert entry_id

    entries = await read_range(stream, start=entry_id)
    matching = [data for _id, data in entries if data.get("nonce") == payload["nonce"]]
    assert matching == [payload]


@pytest.mark.asyncio
async def test_read_new_blocks_until_publish() -> None:
    stream = Stream.HEALTH_UPDATED
    nonce = str(uuid.uuid4())

    last_id = await latest_id(stream)

    payload = {"service": "kis-websocket", "state": "DEGRADED", "nonce": nonce}
    await publish(stream, payload)

    new_entries = await read_new(stream, last_id=last_id, block_ms=2000, count=10)
    matching = [data for _id, data in new_entries if data.get("nonce") == nonce]
    assert matching == [payload]


@pytest.mark.asyncio
async def test_every_declared_stream_accepts_a_publish() -> None:
    for stream in Stream:
        entry_id = await publish(stream, {"probe": stream.value})
        assert entry_id


@pytest.mark.asyncio
async def test_ensure_group_does_not_replay_pre_existing_backlog() -> None:
    """Regression test: a fresh group must start at '$' (now), not '0' (the epoch).

    Starting at '0' means every message ever published to a long-lived
    stream counts as undelivered for a brand new group, so `read_group`
    with a small `count` returns only the oldest historical entries and
    never the message the test (or a real new consumer) actually cares
    about. This is exactly the failure this test guards against.
    """
    stream = Stream.APPROVAL_UPDATED
    group = f"test-group-{uuid.uuid4().hex[:8]}"
    pre_existing_nonce = str(uuid.uuid4())
    new_nonce = str(uuid.uuid4())

    # Published *before* the group exists - must never be delivered to it.
    await publish(stream, {"note": "pre-existing", "nonce": pre_existing_nonce})

    await ensure_group(stream, group)
    await publish(stream, {"note": "new", "nonce": new_nonce})

    delivered = await read_group(stream, group, "consumer-1", count=10, block_ms=2000)
    nonces = {data.get("nonce") for _id, data in delivered}
    assert new_nonce in nonces
    assert pre_existing_nonce not in nonces


@pytest.mark.asyncio
async def test_consumer_group_delivers_and_acks_exactly_once_per_consumer() -> None:
    stream = Stream.ORDER_UPDATED
    group = f"test-group-{uuid.uuid4().hex[:8]}"
    consumer = "test-consumer-1"
    nonce = str(uuid.uuid4())

    await ensure_group(stream, group)
    await publish(stream, {"order_id": "ord-1", "status": "FILLED", "nonce": nonce})

    delivered = await read_group(stream, group, consumer, count=10, block_ms=2000)
    matching = [(entry_id, data) for entry_id, data in delivered if data.get("nonce") == nonce]
    assert len(matching) == 1

    entry_id, _data = matching[0]
    await ack(stream, group, entry_id)

    # A second read for the same group should not redeliver an acked message.
    redelivered = await read_group(stream, group, "test-consumer-2", count=10, block_ms=500)
    still_pending = [d for _id, d in redelivered if d.get("nonce") == nonce]
    assert still_pending == []
