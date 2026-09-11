"""Fill simulation (P20): spread, slippage, partial fill, latency.

Pure over a caller-supplied `MarketSnapshot` - this module never fetches
market data itself. The caller decides which snapshot represents "the
market after this order's simulated latency has elapsed" (a live snapshot
fetched again after waiting `latency_ms`, or the next historical bar in a
replay); `simulate_fill` just prices the order against whatever snapshot it
is given and records the latency that was assumed.

Cost components:
- Spread: a market order pays the touch price on its own side (BUY fills at
  `ask`, SELL fills at `bid`), never the midpoint - the spread itself is a
  cost, not something a simulation should let an order cross for free.
- Slippage: additional adverse move beyond the touch price, sized by how
  large the order is relative to the available liquidity at that price
  (`available_volume`) - a bigger order against thinner liquidity moves the
  price further, via a simple linear participation-rate model.
- Partial fill: an order that asks for more than `available_volume *
  max_participation_rate` only gets that much filled; the rest is reported
  unfilled rather than assumed to fill anyway.
- A limit order that isn't marketable against the snapshot (buy limit below
  the ask, sell limit above the bid) fills nothing - it is never optimistic
  about a price the snapshot doesn't show as available.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_PARTICIPATION_RATE = 0.1
DEFAULT_SLIPPAGE_COEFFICIENT = 0.5
"""At 100% participation rate (order size == all available liquidity), the
adverse move is `DEFAULT_SLIPPAGE_COEFFICIENT` times the spread - a rough,
conservative stand-in for a real market-impact model."""


@dataclass(frozen=True)
class MarketSnapshot:
    bid: float
    ask: float
    available_volume: float
    """Quantity available at the touch price for the side about to trade."""


@dataclass(frozen=True)
class SimulatedFill:
    fill_quantity: float
    fill_price: float
    slippage_amount: float
    """Adverse move per unit beyond the touch price, in price terms."""
    latency_ms: int
    partial: bool


def _touch_price(side: str, snapshot: MarketSnapshot) -> float:
    return snapshot.ask if side == "BUY" else snapshot.bid


def _is_marketable(side: str, limit_price: float | None, snapshot: MarketSnapshot) -> bool:
    if limit_price is None:
        return True
    if side == "BUY":
        return limit_price >= snapshot.ask
    return limit_price <= snapshot.bid


def simulate_fill(
    *,
    side: str,
    quantity: float,
    order_type: str,
    limit_price: float | None,
    snapshot: MarketSnapshot,
    latency_ms: int = 0,
    max_participation_rate: float = DEFAULT_MAX_PARTICIPATION_RATE,
    slippage_coefficient: float = DEFAULT_SLIPPAGE_COEFFICIENT,
) -> SimulatedFill:
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")

    if order_type == "LIMIT" and not _is_marketable(side, limit_price, snapshot):
        return SimulatedFill(0.0, 0.0, 0.0, latency_ms, partial=False)

    cap = snapshot.available_volume * max_participation_rate
    fill_quantity = min(quantity, cap) if cap > 0 else 0.0
    partial = fill_quantity < quantity

    if fill_quantity <= 0:
        return SimulatedFill(0.0, 0.0, 0.0, latency_ms, partial=True)

    spread = snapshot.ask - snapshot.bid
    participation = fill_quantity / snapshot.available_volume if snapshot.available_volume > 0 else 0.0
    slippage_amount = spread * slippage_coefficient * participation

    touch = _touch_price(side, snapshot)
    direction = 1 if side == "BUY" else -1
    fill_price = touch + direction * slippage_amount

    return SimulatedFill(fill_quantity, fill_price, slippage_amount, latency_ms, partial)
