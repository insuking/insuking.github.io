"""Upbit public WebSocket client (P7): ticker/trade/orderbook, 24/7 reconnect,
heartbeat/staleness detection, subscription restore.

No API key needed - this is all public market data. Verified real protocol
(see docs/UPBIT_NOTES.md for what was checked and how):
- `wss://api.upbit.com/websocket/v1`
- Subscribe frame: a JSON array `[{"ticket": ...}, {"type": ..., "codes": [...]}, ..., {"format": "DEFAULT"}]`.
- Messages are plain JSON with a `type` field to dispatch on - no envelope
  to unpack, unlike KIS (P3).

Design notes shared with `KisWebSocketClient` (P3): `connect` is injected
for unit testing (mocks only in unit tests, never claimed as a real
connection), subscriptions are replayed on every reconnect, and reconnect
backoff is exponential and capped.

New in this client: an explicit staleness watchdog. Upbit can leave a TCP
connection looking "open" while silently no longer delivering messages;
waiting for `ConnectionClosed` alone would miss that, so a background task
force-closes the socket (triggering the normal reconnect path) if no
message has arrived within `stale_timeout_seconds`.

24h-memory note: this client holds no per-message history or unbounded
buffer - every message is parsed and published immediately, and the only
growing-with-time state is the subscription set itself (bounded by how many
symbols are ever subscribed, not by how long the process has been running).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import websockets

from app.core.config import Settings, get_settings
from app.events import Stream, publish
from app.integrations.upbit.parsing import parse_orderbook, parse_ticker, parse_trade

log = logging.getLogger(__name__)

PublishFn = Callable[[Stream, dict[str, Any]], Awaitable[str]]

DEFAULT_STALE_TIMEOUT_SECONDS = 90.0
_WATCHDOG_POLL_INTERVAL_SECONDS = 5.0


class _WSConnection(Protocol):
    async def send(self, message: str) -> None: ...
    async def close(self) -> None: ...
    def __aiter__(self) -> Any: ...


class UpbitWebSocketClient:
    def __init__(
        self,
        settings: Settings | None = None,
        connect: Callable[[str], Any] = websockets.connect,
        publish_fn: PublishFn = publish,
        max_backoff_seconds: float = 30.0,
        stale_timeout_seconds: float = DEFAULT_STALE_TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings or get_settings()
        self._connect = connect
        self._publish = publish_fn
        self._max_backoff = max_backoff_seconds
        self._stale_timeout = stale_timeout_seconds
        self._subscriptions: dict[str, set[str]] = {}
        self._ws: _WSConnection | None = None
        self._running = False
        self._last_message_at = 0.0

    @property
    def subscriptions(self) -> dict[str, frozenset[str]]:
        return {msg_type: frozenset(codes) for msg_type, codes in self._subscriptions.items()}

    async def subscribe(self, message_type: str, codes: list[str]) -> None:
        self._subscriptions.setdefault(message_type, set()).update(codes)
        if self._ws is not None:
            await self._send_subscribe(self._ws)

    def _build_subscribe_frame(self) -> str:
        ticket = {"ticket": str(uuid.uuid4())[:8]}
        channels = [
            {"type": msg_type, "codes": sorted(codes)}
            for msg_type, codes in sorted(self._subscriptions.items())
        ]
        return json.dumps([ticket, *channels, {"format": "DEFAULT"}])

    async def _send_subscribe(self, ws: _WSConnection) -> None:
        if not self._subscriptions:
            return
        await ws.send(self._build_subscribe_frame())

    async def run(self) -> None:
        """Connect and process messages until `stop()`, reconnecting on drop or staleness."""
        self._running = True
        backoff = 1.0
        while self._running:
            try:
                async with self._connect(self._settings.upbit_ws_url) as ws:
                    self._ws = ws
                    backoff = 1.0
                    self._last_message_at = time.monotonic()
                    await self._send_subscribe(ws)

                    watchdog = asyncio.create_task(self._staleness_watchdog(ws))
                    try:
                        async for raw in ws:
                            self._last_message_at = time.monotonic()
                            await self._handle_message(raw)
                    finally:
                        watchdog.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await watchdog
            except (websockets.ConnectionClosed, OSError) as exc:
                log.warning("Upbit websocket dropped, reconnecting: %s", exc)
            finally:
                self._ws = None

            if not self._running:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self._max_backoff)

    async def _staleness_watchdog(self, ws: _WSConnection) -> None:
        """Force-close a connection that has gone silent past `stale_timeout_seconds`."""
        while True:
            await asyncio.sleep(_WATCHDOG_POLL_INTERVAL_SECONDS)
            if time.monotonic() - self._last_message_at > self._stale_timeout:
                log.warning("Upbit websocket stale - forcing reconnect")
                await ws.close()
                return

    async def stop(self) -> None:
        self._running = False
        if self._ws is not None:
            await self._ws.close()

    async def _handle_message(self, raw: str | bytes) -> None:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        message = json.loads(text)
        msg_type = message.get("type")

        if msg_type == "trade":
            trade = parse_trade(message)
            await self._publish(Stream.MARKET_TRADE, trade.model_dump(mode="json"))
        elif msg_type == "orderbook":
            orderbook = parse_orderbook(message)
            await self._publish(Stream.MARKET_ORDERBOOK, orderbook.model_dump(mode="json"))
        elif msg_type == "ticker":
            quote = parse_ticker(message)
            await self._publish(Stream.MARKET_TICKER, quote.model_dump(mode="json"))
