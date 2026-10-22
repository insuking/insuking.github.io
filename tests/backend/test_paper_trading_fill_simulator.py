"""P20 acceptance: fill_simulator.py's spread/slippage/partial-fill/latency
behaviour - a market order pays the touch price plus size-proportional
slippage, a limit order that isn't marketable fills nothing, and an order
larger than the participation cap only partially fills.
"""

import pytest

from app.paper_trading.fill_simulator import MarketSnapshot, simulate_fill

pytestmark = pytest.mark.P20

_SNAPSHOT = MarketSnapshot(bid=99.0, ask=101.0, available_volume=1000.0)


def test_market_buy_fills_at_or_above_the_ask() -> None:
    fill = simulate_fill(
        side="BUY", quantity=1.0, order_type="MARKET", limit_price=None, snapshot=_SNAPSHOT
    )
    assert fill.fill_quantity == pytest.approx(1.0)
    assert fill.fill_price >= _SNAPSHOT.ask
    assert fill.partial is False


def test_market_sell_fills_at_or_below_the_bid() -> None:
    fill = simulate_fill(
        side="SELL", quantity=1.0, order_type="MARKET", limit_price=None, snapshot=_SNAPSHOT
    )
    assert fill.fill_quantity == pytest.approx(1.0)
    assert fill.fill_price <= _SNAPSHOT.bid


def test_larger_order_incurs_more_slippage_than_smaller_order() -> None:
    small = simulate_fill(
        side="BUY", quantity=10.0, order_type="MARKET", limit_price=None, snapshot=_SNAPSHOT
    )
    large = simulate_fill(
        side="BUY", quantity=90.0, order_type="MARKET", limit_price=None, snapshot=_SNAPSHOT
    )
    assert large.slippage_amount > small.slippage_amount
    assert large.fill_price > small.fill_price


def test_order_beyond_participation_cap_partially_fills() -> None:
    fill = simulate_fill(
        side="BUY",
        quantity=1000.0,
        order_type="MARKET",
        limit_price=None,
        snapshot=_SNAPSHOT,
        max_participation_rate=0.1,
    )
    assert fill.partial is True
    assert fill.fill_quantity == pytest.approx(100.0)


def test_marketable_buy_limit_fills() -> None:
    fill = simulate_fill(
        side="BUY", quantity=1.0, order_type="LIMIT", limit_price=101.5, snapshot=_SNAPSHOT
    )
    assert fill.fill_quantity == pytest.approx(1.0)


def test_unmarketable_buy_limit_does_not_fill() -> None:
    fill = simulate_fill(
        side="BUY", quantity=1.0, order_type="LIMIT", limit_price=100.0, snapshot=_SNAPSHOT
    )
    assert fill.fill_quantity == 0.0
    assert fill.partial is False


def test_unmarketable_sell_limit_does_not_fill() -> None:
    fill = simulate_fill(
        side="SELL", quantity=1.0, order_type="LIMIT", limit_price=100.0, snapshot=_SNAPSHOT
    )
    assert fill.fill_quantity == 0.0


def test_zero_available_volume_fills_nothing() -> None:
    empty = MarketSnapshot(bid=99.0, ask=101.0, available_volume=0.0)
    fill = simulate_fill(side="BUY", quantity=1.0, order_type="MARKET", limit_price=None, snapshot=empty)
    assert fill.fill_quantity == 0.0
    assert fill.partial is True


def test_latency_is_echoed_back_unchanged() -> None:
    fill = simulate_fill(
        side="BUY", quantity=1.0, order_type="MARKET", limit_price=None, snapshot=_SNAPSHOT, latency_ms=250
    )
    assert fill.latency_ms == 250


def test_invalid_side_raises() -> None:
    with pytest.raises(ValueError, match="BUY or SELL"):
        simulate_fill(
            side="HOLD", quantity=1.0, order_type="MARKET", limit_price=None, snapshot=_SNAPSHOT  # type: ignore[arg-type]
        )
