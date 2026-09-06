"""SQLAlchemy ORM tables (P2, extended in P12/P13).

Maps the P1 domain model onto persistent storage. Table names and grouping
follow docs/MASTER_SPEC.md section P2 exactly:

    market_ticks, candles, features, signals, recommendations, approvals,
    trade_plans, orders, fills, positions, protective_orders, system_health,
    incidents, audit_logs, performance

`market_ticks`, `candles`, `features`, `signals`, and `performance` are
time-series tables intended to be TimescaleDB hypertables (see
migrations/versions for the `create_hypertable` call, which is skipped with a
logged warning when the `timescaledb` extension isn't installed - e.g. on a
plain Postgres dev instance - rather than failing the migration outright).

Two tables sit outside that original P2 list, added when a later phase
needed somewhere durable that P2 didn't anticipate: `kakao_accounts` (P12,
OAuth tokens - see app/integrations/kakao/token_store.py) and
`approval_events` (P13, the audit trail docs/MASTER_SPEC.md section E
requires for every approval state transition - see app/approval/service.py).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class MarketTick(Base):
    __tablename__ = "market_ticks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    symbol: Mapped[str] = mapped_column(String, index=True)
    asset_type: Mapped[str] = mapped_column(String)
    exchange: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    price: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    exchange_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    received_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Candle(Base):
    __tablename__ = "candles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    symbol: Mapped[str] = mapped_column(String, index=True)
    interval: Mapped[str] = mapped_column(String)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Feature(Base):
    __tablename__ = "features"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    symbol: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Float)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)


class SignalRow(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    symbol: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    value: Mapped[float] = mapped_column(Float)
    state: Mapped[str | None] = mapped_column(String, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    symbol: Mapped[str] = mapped_column(String, index=True)
    asset_type: Mapped[str] = mapped_column(String)
    score: Mapped[float] = mapped_column(Float)
    state: Mapped[str] = mapped_column(String)
    entry_low: Mapped[float] = mapped_column(Float)
    entry_high: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    t1_price: Mapped[float] = mapped_column(Float)
    t1_percent: Mapped[float] = mapped_column(Float)
    t2_price: Mapped[float] = mapped_column(Float)
    t2_percent: Mapped[float] = mapped_column(Float)
    runner_percent: Mapped[float] = mapped_column(Float)
    expected_max_loss: Mapped[float] = mapped_column(Float)
    risk_reward: Mapped[float] = mapped_column(Float)
    reasons: Mapped[str] = mapped_column(Text, default="[]")
    risks: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    recommendation_id: Mapped[str] = mapped_column(
        String, ForeignKey("recommendations.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str] = mapped_column(String)
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TradePlan(Base):
    __tablename__ = "trade_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    approval_id: Mapped[str] = mapped_column(String, ForeignKey("approvals.id"), index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    initial_qty: Mapped[float] = mapped_column(Float)
    t1_percent: Mapped[float] = mapped_column(Float, default=30.0)
    t2_percent: Mapped[float] = mapped_column(Float, default=30.0)
    runner_percent: Mapped[float] = mapped_column(Float, default=40.0)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    t1_price: Mapped[float] = mapped_column(Float)
    t2_price: Mapped[float] = mapped_column(Float)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    trade_plan_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("trade_plans.id"), nullable=True, index=True
    )
    symbol: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)
    order_type: Mapped[str] = mapped_column(String)
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String)
    broker: Mapped[str] = mapped_column(String)
    broker_order_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Fill(Base):
    __tablename__ = "fills"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    order_id: Mapped[str] = mapped_column(String, ForeignKey("orders.id"), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    symbol: Mapped[str] = mapped_column(String, index=True)
    asset_type: Mapped[str] = mapped_column(String)
    quantity: Mapped[float] = mapped_column(Float)
    avg_entry_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float] = mapped_column(Float)
    state: Mapped[str] = mapped_column(String)
    guardian_active: Mapped[bool] = mapped_column(Boolean, default=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProtectiveOrder(Base):
    """Stop-loss / take-profit orders guarding an open position (P16/P17)."""

    __tablename__ = "protective_orders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    position_id: Mapped[str] = mapped_column(String, ForeignKey("positions.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # STOP | T1 | T2 | TRAILING
    trigger_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SystemHealthRow(Base):
    __tablename__ = "system_health"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    service: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str] = mapped_column(String)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Incident(Base):
    """See docs/MASTER_SPEC.md section R."""

    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    service: Mapped[str] = mapped_column(String, index=True)
    severity: Mapped[str] = mapped_column(String)
    failure_type: Mapped[str] = mapped_column(String)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    safe_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovery_attempts: Mapped[int] = mapped_column(Integer, default=0)
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_result: Mapped[str | None] = mapped_column(String, nullable=True)
    human_action_required: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    actor: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String)
    subject_type: Mapped[str] = mapped_column(String)
    subject_id: Mapped[str] = mapped_column(String, index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Performance(Base):
    __tablename__ = "performance"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    win_count: Mapped[int] = mapped_column(Integer, default=0)
    loss_count: Mapped[int] = mapped_column(Integer, default=0)


class KakaoAccount(Base):
    """One user's Kakao Login OAuth tokens (P12).

    `user_id` is this application's own user identifier (the same value
    `Approval.user_id` carries) - `kakao_user_id` is Kakao's own per-app
    numeric id, kept separately since nothing guarantees the two schemes
    ever coincide.
    """

    __tablename__ = "kakao_accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    kakao_user_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    access_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    talk_message_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalEvent(Base):
    """One state transition (or a non-terminal decision like HOLD) in an
    approval's lifecycle (P13) - docs/MASTER_SPEC.md section E requires this
    audit trail. `from_state` is null for the row created alongside the
    approval itself (there is no prior state yet). `detail` is a JSON blob
    (e.g. `{"override_amount": ...}` or `{"reasons": [...]}` from P14's
    revalidation) - free-form because what's worth recording differs by
    transition, not a fixed schema.
    """

    __tablename__ = "approval_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    approval_id: Mapped[str] = mapped_column(String, ForeignKey("approvals.id"), index=True)
    from_state: Mapped[str | None] = mapped_column(String, nullable=True)
    to_state: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)  # a user_id, or "system"
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
