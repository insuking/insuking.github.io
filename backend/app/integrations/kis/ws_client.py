"""KIS real-time WebSocket client (P3): tick + orderbook, reconnect, subscription restore.

Design notes:
- `_connect` is injected (defaults to `websockets.connect`) so unit tests can
  supply a fake connection instead of hitting the network - the master spec
  allows mocks in unit tests, never in integration tests.
- Subscriptions are tracked in `_subscriptions` and replayed on every
  reconnect, satisfying the P3 "subscription restore" requirement.
- Reconnect backoff is exponential, capped, and does not raise out of `run()`
  - a dropped socket is not this client's failure mode to propagate, it's
    exactly what it exists to recover from.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import websockets

from app.core.config import Settings, get_settings
from app.events import Stream, publish
from app.integrations.kis.parsing import (
    is_pingpong,
    is_realtime_data_message,
    parse_envelope,
    record_to_orderbook,
    record_to_trade,
)

log = logging.getLogger(__name__)

PublishFn = Callable[[Stream, dict[str, Any]], Awaitable[str]]


class _WSConnection(Protocol):
    async def send(self, message: str) -> None: ...
    def __aiter__(self) -> Any: ...


class _ApprovalKeySource(Protocol):
    """What this client needs from KisAuth - just the WS approval key.

    Typed as a Protocol rather than the concrete `KisAuth` class so unit
    tests can inject a minimal fake without subclassing or ignoring mypy.
    """

    async def get_ws_approval_key(self) -> str: ...


class KisWebSocketClient:
    def __init__(
        self,
        auth: _ApprovalKeySource,
        settings: Settings | None = None,
        connect: Callable[[str], Any] = websockets.connect,
        publish_fn: PublishFn = publish,
        max_backoff_seconds: float = 30.0,
    ) -> None:
        self._auth = auth
        self._settings = settings or get_settings()
        self._connect = connect
        self._publish = publish_fn
        self._max_backoff = max_backoff_seconds
        self._subscriptions: set[tuple[str, str]] = set()
        self._ws: _WSConnection | None = None
        self._running = False

    @property
    def subscriptions(self) -> frozenset[tuple[str, str]]:
        return frozenset(self._subscriptions)

    async def subscribe(self, tr_id: str, symbol: str) -> None:
        self._subscriptions.add((tr_id, symbol))
        if self._ws is not None:
            await self._send_subscribe(self._ws, tr_id, symbol)

    async def _send_subscribe(self, ws: _WSConnection, tr_id: str, symbol: str) -> None:
        approval_key = await self._auth.get_ws_approval_key()
        frame = {
            "header": {
                "approval_key": approval_key,
                "custtype": "P",
                "tr_type": "1",
                "content-type": "utf-8",
            },
            "body": {"input": {"tr_id": tr_id, "tr_key": symbol}},
        }
        await ws.send(json.dumps(frame))

    async def run(self) -> None:
        """Connect and process messages until `stop()`, reconnecting on drop."""
        self._running = True
        backoff = 1.0
        while self._running:
            try:
                async with self._connect(self._settings.kis_ws_url) as ws:
                    self._ws = ws
                    backoff = 1.0
                    for tr_id, symbol in sorted(self._subscriptions):
                        await self._send_subscribe(ws, tr_id, symbol)
                    async for raw in ws:
                        await self._handle_message(ws, raw)
            except (websockets.ConnectionClosed, OSError) as exc:
                log.warning("KIS websocket dropped, reconnecting: %s", exc)
            finally:
                self._ws = None

            if not self._running:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self._max_backoff)

    async def stop(self) -> None:
        self._running = False
        if self._ws is not None:
            close = getattr(self._ws, "close", None)
            if close is not None:
                await close()

    async def _handle_message(self, ws: _WSConnection, raw: str) -> None:
        if is_realtime_data_message(raw):
            envelope = parse_envelope(raw)
            for record in envelope.records:
                if envelope.tr_id == "H0STCNT0":
                    trade = record_to_trade(record)
                    await self._publish(Stream.MARKET_TRADE, trade.model_dump(mode="json"))
                elif envelope.tr_id == "H0STASP0":
                    orderbook = record_to_orderbook(record)
                    await self._publish(Stream.MARKET_ORDERBOOK, orderbook.model_dump(mode="json"))
        elif is_pingpong(raw):
            await ws.send(raw)
