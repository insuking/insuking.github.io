"""Common domain model (P1).

Pydantic v2 models shared by every later phase. Kept intentionally free of
persistence and API-framework concerns - P2 maps these onto Timescale tables
and Redis stream payloads, P6+ builds the recommendation/approval/execution
flow on top of them. See docs/MASTER_SPEC.md sections B-J for the semantics
each field encodes.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class AssetType(str, Enum):
    STOCK = "STOCK"
    CRYPTO = "CRYPTO"


class Exchange(str, Enum):
    KRX = "KRX"
    UPBIT = "UPBIT"


class Market(str, Enum):
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"
    UPBIT_KRW = "UPBIT_KRW"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class PositionState(str, Enum):
    OPEN = "OPEN"
    T1_FILLED = "T1_FILLED"
    T2_FILLED = "T2_FILLED"
    RUNNER = "RUNNER"
    CLOSED = "CLOSED"


class ApprovalState(str, Enum):
    """See docs/MASTER_SPEC.md section E."""

    CREATED = "CREATED"
    NOTIFIED = "NOTIFIED"
    OPENED = "OPENED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    EXECUTED = "EXECUTED"
    BLOCKED_BY_RISK = "BLOCKED_BY_RISK"


class HealthState(str, Enum):
    """See docs/MASTER_SPEC.md section Q."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    RECOVERING = "RECOVERING"
    PAUSED = "PAUSED"
    CRITICAL = "CRITICAL"
    OFFLINE = "OFFLINE"


class DomainModel(BaseModel):
    """Base class: strict field validation, immutable-by-convention DTOs."""

    model_config = {"extra": "forbid"}


class Quote(DomainModel):
    symbol: str
    asset_type: AssetType
    exchange: Exchange
    market: Market
    price: float = Field(gt=0)
    bid: float | None = Field(default=None, ge=0)
    ask: float | None = Field(default=None, ge=0)
    volume: float = Field(ge=0)
    exchange_ts: datetime
    received_ts: datetime


class Trade(DomainModel):
    symbol: str
    asset_type: AssetType
    price: float = Field(gt=0)
    quantity: float = Field(gt=0)
    side: OrderSide
    exchange_ts: datetime
    received_ts: datetime


class OrderBookLevel(DomainModel):
    price: float = Field(gt=0)
    quantity: float = Field(ge=0)


class OrderBook(DomainModel):
    symbol: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    exchange_ts: datetime
    received_ts: datetime


class Candle(DomainModel):
    symbol: str
    interval: str
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    open_time: datetime
    close_time: datetime


class Signal(DomainModel):
    symbol: str
    name: str
    value: float
    state: str | None = None
    computed_at: datetime


class Recommendation(DomainModel):
    id: str
    symbol: str
    asset_type: AssetType
    score: float = Field(ge=0, le=100)
    state: str
    entry_low: float = Field(gt=0)
    entry_high: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    t1_price: float = Field(gt=0)
    t1_percent: float = Field(gt=0, le=100)
    t2_price: float = Field(gt=0)
    t2_percent: float = Field(gt=0, le=100)
    runner_percent: float = Field(gt=0, le=100)
    expected_max_loss: float = Field(ge=0)
    risk_reward: float = Field(gt=0)
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    created_at: datetime
    expires_at: datetime


class Approval(DomainModel):
    id: str
    recommendation_id: str
    user_id: str
    state: ApprovalState
    token_hash: str
    created_at: datetime
    notified_at: datetime | None = None
    opened_at: datetime | None = None
    decided_at: datetime | None = None
    expires_at: datetime


class TradePlan(DomainModel):
    id: str
    approval_id: str
    symbol: str
    initial_qty: float = Field(gt=0)
    t1_percent: float = Field(default=30.0, gt=0, le=100)
    t2_percent: float = Field(default=30.0, gt=0, le=100)
    runner_percent: float = Field(default=40.0, gt=0, le=100)
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    t1_price: float = Field(gt=0)
    t2_price: float = Field(gt=0)


class Order(DomainModel):
    id: str
    trade_plan_id: str | None = None
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float = Field(gt=0)
    price: float | None = Field(default=None, gt=0)
    status: OrderStatus
    broker: str
    broker_order_id: str | None = None
    created_at: datetime
    updated_at: datetime


class Fill(DomainModel):
    id: str
    order_id: str
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    filled_at: datetime


class Position(DomainModel):
    id: str
    symbol: str
    asset_type: AssetType
    quantity: float = Field(ge=0)
    avg_entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    state: PositionState
    guardian_active: bool = True
    opened_at: datetime
    updated_at: datetime


class RiskState(DomainModel):
    as_of: datetime
    daily_loss: float
    daily_loss_limit: float = Field(gt=0)
    exposure: float = Field(ge=0)
    exposure_limit: float = Field(gt=0)
    open_positions: int = Field(ge=0)
    max_positions: int = Field(gt=0)
    consecutive_stops: int = Field(ge=0)
    kill_switch_active: bool = False
    kill_switch_reason: str | None = None


class SystemHealth(DomainModel):
    service: str
    state: HealthState
    detected_at: datetime
    message: str | None = None
