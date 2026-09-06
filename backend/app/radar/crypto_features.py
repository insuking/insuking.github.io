"""Crypto-specific feature calculations (P8).

VWAP, RVOL, turnover, and liquidity are pure math over a `Candle` series with
nothing stock-specific about them - they're reused from `app.radar.features`
unchanged rather than duplicated here. Likewise "BTC regime" is exactly
`app.radar.regime.classify_market_regime` run against BTC-KRW candles
instead of a benchmark index, and "BTC relative strength" is
`app.radar.features.relative_strength` run against BTC-KRW candles instead
of KOSPI - both re-exported below under crypto-flavored names so P9 (crypto
radar) doesn't need to reach into a stock-named module to use them.

What's genuinely new here: realized volatility, orderbook spread/imbalance,
slippage estimation, pump-risk scoring, and a feed-anomaly guard - none of
which existed in P4 because P4 had no orderbook history and stocks don't
carry the same pump-and-dump risk profile crypto does.
"""

from __future__ import annotations

import math

from app.models.domain import Candle, OrderBook, OrderSide
from app.radar.features import (
    liquidity_score,
    relative_volume,
    turnover,
    turnover_acceleration,
    vwap,
    vwap_series,
)
from app.radar.features import (
    relative_strength as relative_strength_vs_btc,
)
from app.radar.regime import MarketRegime
from app.radar.regime import classify_market_regime as classify_btc_regime

__all__ = [
    "MarketRegime",
    "classify_btc_regime",
    "detect_feed_anomaly",
    "estimate_slippage",
    "liquidity_score",
    "orderbook_imbalance",
    "pump_risk_score",
    "realized_volatility",
    "relative_strength_vs_btc",
    "relative_volume",
    "spread",
    "turnover",
    "turnover_acceleration",
    "vwap",
    "vwap_series",
]


def realized_volatility(candles: list[Candle]) -> float:
    """Population stdev of consecutive close-to-close returns (fractional)."""
    if len(candles) < 2:
        return 0.0
    returns = [
        (candles[i].close - candles[i - 1].close) / candles[i - 1].close
        for i in range(1, len(candles))
        if candles[i - 1].close > 0
    ]
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    return math.sqrt(variance)


def spread(orderbook: OrderBook) -> float:
    """Fractional best bid-ask spread. 0.0 if either side of the book is empty."""
    if not orderbook.bids or not orderbook.asks:
        return 0.0
    best_bid = orderbook.bids[0].price
    best_ask = orderbook.asks[0].price
    mid = (best_bid + best_ask) / 2
    if mid <= 0:
        return 0.0
    return (best_ask - best_bid) / mid


def orderbook_imbalance(orderbook: OrderBook) -> float:
    """(bid volume - ask volume) / total volume, in [-1, 1]. Positive = buy-side heavier."""
    total_bid = sum(level.quantity for level in orderbook.bids)
    total_ask = sum(level.quantity for level in orderbook.asks)
    total = total_bid + total_ask
    if total <= 0:
        return 0.0
    return (total_bid - total_ask) / total


def estimate_slippage(orderbook: OrderBook, side: OrderSide, quantity: float) -> float:
    """Fractional slippage of a market order of `quantity` vs. the best price on that side.

    Walks book levels (asks for a BUY, bids for a SELL) accumulating size
    until filled. Returns 0.0 for a non-positive quantity or a book that
    can't fill the order - it's better to say "unknown" than to fabricate a
    slippage number for size that isn't actually in the book.
    """
    levels = orderbook.asks if side == OrderSide.BUY else orderbook.bids
    if quantity <= 0 or not levels:
        return 0.0

    best_price = levels[0].price
    remaining = quantity
    notional = 0.0
    filled = 0.0
    for level in levels:
        take = min(remaining, level.quantity)
        notional += take * level.price
        filled += take
        remaining -= take
        if remaining <= 0:
            break

    if remaining > 0 or filled <= 0:
        return 0.0
    avg_price = notional / filled
    return abs(avg_price - best_price) / best_price


def pump_risk_score(candles: list[Candle], lookback: int = 10) -> float:
    """0-100 heuristic pump-and-dump risk from the last `lookback` bars.

    Combines three signals that all need to be elevated together - price
    run-up, volume multiple vs. the preceding baseline, and realized
    volatility - so a single big-but-ordinary bar doesn't trip it, and a
    crash (price falling, not rising) scores low here even with heavy
    volume and volatility, since `price_change` is clamped to >= 0 before
    contributing. Distinguishing "pump" from "crash" this way is
    deliberate: see test_crypto_features.py's BTC-crash fixture.
    """
    if len(candles) < lookback + 1:
        return 0.0

    window = candles[-lookback:]
    baseline = candles[:-lookback]

    price_change = (window[-1].close - window[0].close) / window[0].close if window[0].close else 0.0

    window_avg_volume = sum(c.volume for c in window) / len(window)
    baseline_avg_volume = (
        sum(c.volume for c in baseline) / len(baseline) if baseline else window_avg_volume
    )
    volume_multiple = window_avg_volume / baseline_avg_volume if baseline_avg_volume > 0 else 1.0

    volatility = realized_volatility(window)

    score = 0.0
    score += max(0.0, min(price_change * 100, 50.0))
    score += max(0.0, min((volume_multiple - 1.0) * 10, 30.0))
    score += max(0.0, min(volatility * 200, 20.0))
    return max(0.0, min(100.0, score))


def detect_feed_anomaly(candles: list[Candle], max_single_bar_move: float = 0.5) -> bool:
    """True if the latest bar moved implausibly far from the prior close in one tick.

    A crude but effective guard against a single bad print (fat-finger
    tick, exchange glitch - e.g. an extra zero) corrupting every feature
    computed on top of it - not a full data-quality pipeline, just the one
    check P8 asks for. Non-positive prices are already rejected by the
    `Candle` model itself (`Field(gt=0)`), so that class of bad print can't
    reach this function at all.
    """
    if len(candles) < 2:
        return False
    prev_close = candles[-2].close
    latest_close = candles[-1].close
    move = abs(latest_close - prev_close) / prev_close
    return move > max_single_bar_move
