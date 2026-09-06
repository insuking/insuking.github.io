from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.domain import (
    Approval,
    ApprovalState,
    AssetType,
    Candle,
    Exchange,
    Fill,
    HealthState,
    Market,
    Order,
    OrderBook,
    OrderBookLevel,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionState,
    Quote,
    Recommendation,
    RiskState,
    Signal,
    SystemHealth,
    Trade,
    TradePlan,
)

pytestmark = pytest.mark.P1

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_quote_round_trips_through_json() -> None:
    quote = Quote(
        symbol="005930",
        asset_type=AssetType.STOCK,
        exchange=Exchange.KRX,
        market=Market.KOSPI,
        price=71000,
        bid=70900,
        ask=71100,
        volume=1234.0,
        exchange_ts=NOW,
        received_ts=NOW,
    )

    restored = Quote.model_validate_json(quote.model_dump_json())

    assert restored == quote


def test_quote_rejects_non_positive_price() -> None:
    with pytest.raises(ValidationError):
        Quote(
            symbol="005930",
            asset_type=AssetType.STOCK,
            exchange=Exchange.KRX,
            market=Market.KOSPI,
            price=0,
            volume=1.0,
            exchange_ts=NOW,
            received_ts=NOW,
        )


def test_quote_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Quote(
            symbol="005930",
            asset_type=AssetType.STOCK,
            exchange=Exchange.KRX,
            market=Market.KOSPI,
            price=100,
            volume=1.0,
            exchange_ts=NOW,
            received_ts=NOW,
            unexpected_field="nope",  # type: ignore[call-arg]  # intentional: asserts rejection
        )


def test_trade_round_trip() -> None:
    trade = Trade(
        symbol="KRW-XRP",
        asset_type=AssetType.CRYPTO,
        price=4100.5,
        quantity=12.0,
        side=OrderSide.BUY,
        exchange_ts=NOW,
        received_ts=NOW,
    )
    assert Trade.model_validate_json(trade.model_dump_json()) == trade


def test_orderbook_nested_levels_round_trip() -> None:
    book = OrderBook(
        symbol="KRW-BTC",
        bids=[OrderBookLevel(price=100.0, quantity=1.0)],
        asks=[OrderBookLevel(price=101.0, quantity=2.0)],
        exchange_ts=NOW,
        received_ts=NOW,
    )
    restored = OrderBook.model_validate_json(book.model_dump_json())
    assert restored == book
    assert restored.bids[0].price == 100.0


def test_candle_round_trip() -> None:
    candle = Candle(
        symbol="KRW-XRP",
        interval="1m",
        open=100,
        high=110,
        low=95,
        close=105,
        volume=1000,
        open_time=NOW,
        close_time=NOW,
    )
    assert Candle.model_validate_json(candle.model_dump_json()) == candle


def test_signal_allows_optional_state() -> None:
    signal = Signal(symbol="005930", name="RVOL", value=2.3, computed_at=NOW)
    assert signal.state is None
    assert Signal.model_validate_json(signal.model_dump_json()) == signal


def test_recommendation_score_bounds() -> None:
    with pytest.raises(ValidationError):
        Recommendation(
            id="rec-1",
            symbol="KRW-XRP",
            asset_type=AssetType.CRYPTO,
            score=150,
            state="CONFIRMED_BREAKOUT",
            entry_low=4080,
            entry_high=4130,
            stop_price=3980,
            t1_price=4270,
            t1_percent=30,
            t2_price=4450,
            t2_percent=30,
            runner_percent=40,
            expected_max_loss=9500,
            risk_reward=2.1,
            created_at=NOW,
            expires_at=NOW,
        )


def test_recommendation_round_trip_with_defaults() -> None:
    rec = Recommendation(
        id="rec-1",
        symbol="KRW-XRP",
        asset_type=AssetType.CRYPTO,
        score=92,
        state="CONFIRMED_BREAKOUT",
        entry_low=4080,
        entry_high=4130,
        stop_price=3980,
        t1_price=4270,
        t1_percent=30,
        t2_price=4450,
        t2_percent=30,
        runner_percent=40,
        expected_max_loss=9500,
        risk_reward=2.1,
        created_at=NOW,
        expires_at=NOW,
    )
    assert rec.reasons == []
    assert rec.risks == []
    assert Recommendation.model_validate_json(rec.model_dump_json()) == rec


def test_approval_state_transitions_are_enum_constrained() -> None:
    approval = Approval(
        id="appr-1",
        recommendation_id="rec-1",
        user_id="user-1",
        state=ApprovalState.NOTIFIED,
        token_hash="deadbeef",
        created_at=NOW,
        expires_at=NOW,
    )
    assert Approval.model_validate_json(approval.model_dump_json()) == approval

    with pytest.raises(ValidationError):
        Approval(
            id="appr-1",
            recommendation_id="rec-1",
            user_id="user-1",
            state="NOT_A_REAL_STATE",  # type: ignore[arg-type]  # intentional: asserts rejection
            token_hash="deadbeef",
            created_at=NOW,
            expires_at=NOW,
        )


def test_trade_plan_default_split_is_30_30_40() -> None:
    plan = TradePlan(
        id="plan-1",
        approval_id="appr-1",
        symbol="KRW-XRP",
        initial_qty=100,
        entry_price=4100,
        stop_price=3980,
        t1_price=4270,
        t2_price=4450,
    )
    assert (plan.t1_percent, plan.t2_percent, plan.runner_percent) == (30.0, 30.0, 40.0)
    assert TradePlan.model_validate_json(plan.model_dump_json()) == plan


def test_order_and_fill_round_trip() -> None:
    order = Order(
        id="ord-1",
        symbol="KRW-XRP",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=4100,
        status=OrderStatus.SUBMITTED,
        broker="UPBIT",
        created_at=NOW,
        updated_at=NOW,
    )
    fill = Fill(id="fill-1", order_id=order.id, quantity=30, price=4270, filled_at=NOW)

    assert Order.model_validate_json(order.model_dump_json()) == order
    assert Fill.model_validate_json(fill.model_dump_json()) == fill


def test_position_round_trip() -> None:
    position = Position(
        id="pos-1",
        symbol="KRW-XRP",
        asset_type=AssetType.CRYPTO,
        quantity=70,
        avg_entry_price=4100,
        stop_price=4100,
        state=PositionState.T1_FILLED,
        opened_at=NOW,
        updated_at=NOW,
    )
    assert position.guardian_active is True
    assert Position.model_validate_json(position.model_dump_json()) == position


def test_risk_state_kill_switch_defaults_off() -> None:
    risk = RiskState(
        as_of=NOW,
        daily_loss=0,
        daily_loss_limit=100000,
        exposure=0,
        exposure_limit=500000,
        open_positions=0,
        max_positions=5,
        consecutive_stops=0,
    )
    assert risk.kill_switch_active is False
    assert RiskState.model_validate_json(risk.model_dump_json()) == risk


def test_system_health_round_trip() -> None:
    health = SystemHealth(service="kis-websocket", state=HealthState.DEGRADED, detected_at=NOW)
    assert SystemHealth.model_validate_json(health.model_dump_json()) == health
