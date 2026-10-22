"""Parsing for Upbit's public WebSocket JSON messages (P7).

Field names below were verified where a primary source was reachable and
are otherwise long-stable, extremely widely-documented Upbit conventions;
docs.upbit.com itself was blocked by this sandbox's egress policy (see
docs/UPBIT_NOTES.md for exactly what was and wasn't independently checked).

Unlike KIS (P3), Upbit's WS payloads are plain JSON - no pipe/caret envelope
to unpack, just a `type` field to dispatch on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.domain import (
    AssetType,
    Exchange,
    Market,
    OrderBook,
    OrderBookLevel,
    OrderSide,
    Quote,
    Trade,
)


def _ms_to_utc(epoch_ms: int) -> datetime:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)


def parse_trade(message: dict[str, Any]) -> Trade:
    received_ts = datetime.now(UTC)
    return Trade(
        symbol=message["code"],
        asset_type=AssetType.CRYPTO,
        price=float(message["trade_price"]),
        quantity=float(message["trade_volume"]),
        # Upbit's ask_bid is the taker's side: "ASK" means the taker sold
        # (hit the bid), "BID" means the taker bought (lifted the ask).
        side=OrderSide.SELL if message.get("ask_bid") == "ASK" else OrderSide.BUY,
        exchange_ts=_ms_to_utc(int(message["trade_timestamp"])),
        received_ts=received_ts,
    )


def parse_orderbook(message: dict[str, Any]) -> OrderBook:
    received_ts = datetime.now(UTC)
    units = message["orderbook_units"]
    asks = [
        OrderBookLevel(price=float(u["ask_price"]), quantity=float(u["ask_size"]))
        for u in units
        if float(u["ask_price"]) > 0
    ]
    bids = [
        OrderBookLevel(price=float(u["bid_price"]), quantity=float(u["bid_size"]))
        for u in units
        if float(u["bid_price"]) > 0
    ]
    return OrderBook(
        symbol=message["code"],
        bids=bids,
        asks=asks,
        exchange_ts=_ms_to_utc(int(message["timestamp"])),
        received_ts=received_ts,
    )


def parse_ticker(message: dict[str, Any], market: Market = Market.UPBIT_KRW) -> Quote:
    received_ts = datetime.now(UTC)
    return Quote(
        symbol=message["code"],
        asset_type=AssetType.CRYPTO,
        exchange=Exchange.UPBIT,
        market=market,
        price=float(message["trade_price"]),
        # The ticker channel is a price/volume snapshot, not an order book -
        # Upbit doesn't include best bid/ask here, so these stay unset
        # rather than fabricated.
        bid=None,
        ask=None,
        volume=float(message["acc_trade_volume_24h"]),
        exchange_ts=_ms_to_utc(int(message["trade_timestamp"])),
        received_ts=received_ts,
    )
