from datetime import UTC, datetime

import pytest

from app.integrations.upbit.parsing import parse_orderbook, parse_ticker, parse_trade
from app.models.domain import OrderSide

pytestmark = pytest.mark.P7


def test_parse_trade_maps_fields_and_converts_timestamp() -> None:
    message = {
        "type": "trade",
        "code": "KRW-BTC",
        "trade_price": 71000000.5,
        "trade_volume": 0.01,
        "ask_bid": "BID",
        "trade_timestamp": 1735000000000,
    }

    trade = parse_trade(message)

    assert trade.symbol == "KRW-BTC"
    assert trade.price == 71000000.5
    assert trade.quantity == 0.01
    assert trade.side == OrderSide.BUY
    assert trade.exchange_ts == datetime.fromtimestamp(1735000000000 / 1000, tz=UTC)


def test_parse_trade_ask_side() -> None:
    message = {
        "type": "trade",
        "code": "KRW-BTC",
        "trade_price": 100.0,
        "trade_volume": 1.0,
        "ask_bid": "ASK",
        "trade_timestamp": 1735000000000,
    }
    assert parse_trade(message).side == OrderSide.SELL


def test_parse_orderbook_maps_levels_and_drops_zero_price_levels() -> None:
    message = {
        "type": "orderbook",
        "code": "KRW-BTC",
        "timestamp": 1735000000000,
        "total_ask_size": 1.5,
        "total_bid_size": 2.5,
        "orderbook_units": [
            {"ask_price": 71100.0, "bid_price": 71000.0, "ask_size": 0.5, "bid_size": 0.4},
            {"ask_price": 0, "bid_price": 70900.0, "ask_size": 0, "bid_size": 0.1},
        ],
    }

    book = parse_orderbook(message)

    assert book.symbol == "KRW-BTC"
    assert len(book.asks) == 1
    assert book.asks[0].price == 71100.0
    assert len(book.bids) == 2
    assert book.exchange_ts == datetime.fromtimestamp(1735000000000 / 1000, tz=UTC)


def test_parse_ticker_leaves_bid_ask_unset() -> None:
    message = {
        "type": "ticker",
        "code": "KRW-BTC",
        "trade_price": 71000000.0,
        "acc_trade_volume_24h": 1234.5,
        "trade_timestamp": 1735000000000,
    }

    quote = parse_ticker(message)

    assert quote.symbol == "KRW-BTC"
    assert quote.price == 71000000.0
    assert quote.volume == 1234.5
    assert quote.bid is None
    assert quote.ask is None
