"""Redis Streams the platform uses as its event bus (P2).

Stream names are exactly as listed in docs/MASTER_SPEC.md section P2, with
one deliberate, documented addition: `MARKET_TICKER`. P2's fixed 9-stream
list was written before P7 (Upbit public WS) added a ticker channel, and
Upbit's ticker payload (a periodic price/volume snapshot) is neither a trade
execution nor an orderbook update, so publishing it onto `market.trade`
would be semantically wrong rather than a mock-data shortcut. This is the
one place in the project where an event bus stream was added beyond the P2
spec text, done here in P7 rather than silently dropping ticker data.

Payloads are always a single JSON-encoded string under the `data` field, so
every stream can carry an arbitrary P1 domain model (or a plain dict)
without a separate schema per stream.
"""

from enum import Enum


class Stream(str, Enum):
    MARKET_TRADE = "market.trade"
    MARKET_ORDERBOOK = "market.orderbook"
    MARKET_TICKER = "market.ticker"
    FEATURE_UPDATED = "feature.updated"
    RADAR_UPDATED = "radar.updated"
    RECOMMENDATION_CREATED = "recommendation.created"
    APPROVAL_UPDATED = "approval.updated"
    ORDER_UPDATED = "order.updated"
    POSITION_UPDATED = "position.updated"
    HEALTH_UPDATED = "health.updated"
