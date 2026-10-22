"""Thin Redis Streams event bus wrapper (P2).

Two consumption modes are exposed because later phases need both:

- `read_range` / `read_new`: simple tailing, used by dashboards and tests.
- `ensure_group` / `read_group` / `ack`: consumer-group semantics (at-least-
  once delivery, per-consumer backlog, `XPENDING`-visible lag) needed once
  Position Guardian (P16) and the self-healing watchdog (P19) depend on
  knowing whether a message was actually processed.

`redis.asyncio`'s type stubs return broad `bytes | str` unions because the
client can be configured either way; this module's `get_redis()` always sets
`decode_responses=True`, so every value really is `str` at runtime. The casts
below encode that guarantee at the one place it matters instead of leaking
`Any`/`bytes | str` through every caller.
"""

from __future__ import annotations

import json
from typing import Any, cast

from app.db.redis_client import get_redis
from app.events.streams import Stream

RedisEvent = tuple[str, dict[str, Any]]

# redis-py's XREAD/XREADGROUP response shape: [(stream_name, [(id, fields), ...]), ...]
_XReadResponse = list[tuple[str, list[tuple[str, dict[str, str]]]]]


def _encode(payload: dict[str, Any]) -> dict[str, str]:
    return {"data": json.dumps(payload)}


def _decode(fields: dict[str, str]) -> dict[str, Any]:
    return json.loads(fields["data"])


async def publish(stream: Stream, payload: dict[str, Any]) -> str:
    redis = get_redis()
    entry_id = await redis.xadd(stream.value, cast(dict[Any, Any], _encode(payload)))
    return cast(str, entry_id)


async def read_range(
    stream: Stream, count: int | None = None, start: str = "-"
) -> list[RedisEvent]:
    """Read entries from `start` (oldest by default) onward, up to `count`.

    On a long-lived stream, `count` alone counts from the very beginning of
    history - a small `count` can silently never reach anything published
    recently. Pass `start=<an entry_id from publish()>` to scope a read to
    "this entry and whatever comes after", independent of how much history
    the stream has accumulated.
    """
    redis = get_redis()
    entries = cast(
        list[tuple[str, dict[str, str]]], await redis.xrange(stream.value, min=start, count=count)
    )
    return [(entry_id, _decode(fields)) for entry_id, fields in entries]


async def latest_id(stream: Stream) -> str:
    """The ID of the most recent entry currently on the stream (or '0' if empty).

    Use this - not `read_range`, which returns oldest-first - to capture a
    tailing position before publishing, e.g.:
    `since = await latest_id(s); await publish(s, payload); await read_new(s, since)`.
    """
    redis = get_redis()
    entries = cast(list[tuple[str, dict[str, str]]], await redis.xrevrange(stream.value, count=1))
    return entries[0][0] if entries else "0"


async def read_new(
    stream: Stream, last_id: str = "$", block_ms: int = 1000, count: int = 10
) -> list[RedisEvent]:
    """Block for up to `block_ms` waiting for entries after `last_id`."""
    redis = get_redis()
    raw = await redis.xread({stream.value: last_id}, block=block_ms, count=count)
    response = cast(_XReadResponse | None, raw)
    if not response:
        return []
    _stream_name, entries = response[0]
    return [(entry_id, _decode(fields)) for entry_id, fields in entries]


async def ensure_group(stream: Stream, group: str) -> None:
    """Create the consumer group starting at '$' (now), not '0' (the epoch).

    A group created at '0' would replay the stream's entire history on its
    first read - on a long-lived stream that means an unbounded backlog
    instead of the new messages a freshly started consumer actually wants.
    A service that genuinely needs the backlog (e.g. a one-off
    reconciliation) can still read it directly with `read_range`.
    """
    redis = get_redis()
    try:
        await redis.xgroup_create(stream.value, group, id="$", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def read_group(
    stream: Stream, group: str, consumer: str, count: int = 10, block_ms: int = 1000
) -> list[RedisEvent]:
    redis = get_redis()
    raw = await redis.xreadgroup(group, consumer, {stream.value: ">"}, count=count, block=block_ms)
    response = cast(_XReadResponse | None, raw)
    if not response:
        return []
    _stream_name, entries = response[0]
    return [(entry_id, _decode(fields)) for entry_id, fields in entries]


async def ack(stream: Stream, group: str, entry_id: str) -> None:
    redis = get_redis()
    await redis.xack(stream.value, group, entry_id)
