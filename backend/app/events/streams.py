"""Redis Streams the platform uses as its event bus (P2).

Stream names are exactly as listed in docs/MASTER_SPEC.md section P2. Payloads
are always a single JSON-encoded string under the `data` field, so every
stream can carry an arbitrary P1 domain model (or a plain dict) without a
separate schema per stream.
"""

from enum import Enum


class Stream(str, Enum):
    MARKET_TRADE = "market.trade"
    MARKET_ORDERBOOK = "market.orderbook"
    FEATURE_UPDATED = "feature.updated"
    RADAR_UPDATED = "radar.updated"
    RECOMMENDATION_CREATED = "recommendation.created"
    APPROVAL_UPDATED = "approval.updated"
    ORDER_UPDATED = "order.updated"
    POSITION_UPDATED = "position.updated"
    HEALTH_UPDATED = "health.updated"
