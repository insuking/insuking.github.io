from datetime import UTC, datetime, timedelta

import pytest

from app.approval.revalidation import (
    RevalidationInput,
    RevalidationThresholds,
    RevalidationVerdict,
    revalidate,
)
from app.db.models import Recommendation as RecommendationRow
from app.models.domain import Candle, OrderBook, OrderBookLevel, RiskState

pytestmark = pytest.mark.P14

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


def _recommendation(**overrides: object) -> RecommendationRow:
    defaults: dict[str, object] = {
        "id": "rec-1",
        "symbol": "KRW-XRP",
        "asset_type": "CRYPTO",
        "score": 80.0,
        "state": "CONFIRMED_BREAKOUT",
        "entry_low": 4000.0,
        "entry_high": 4020.0,
        "stop_price": 3900.0,
        "t1_price": 4100.0,
        "t1_percent": 30.0,
        "t2_price": 4200.0,
        "t2_percent": 30.0,
        "runner_percent": 40.0,
        "expected_max_loss": 5000.0,
        "risk_reward": 2.0,
        "reasons": "[]",
        "risks": "[]",
        "created_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
    }
    defaults.update(overrides)
    return RecommendationRow(**defaults)


def _candle(close: float, high: float | None = None, low: float | None = None, volume: float = 100, minute: int = 0) -> Candle:
    start = NOW.replace(tzinfo=UTC) + timedelta(minutes=minute)
    return Candle(
        symbol="KRW-XRP",
        interval="1m",
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
        volume=volume,
        open_time=start,
        close_time=start + timedelta(minutes=1),
    )


def _base_input(**overrides: object) -> RevalidationInput:
    defaults: dict[str, object] = {
        "now": NOW,
        "approval_expires_at": NOW + timedelta(minutes=2),
        "recommendation": _recommendation(),
        "current_price": 4010.0,
        "recent_candles": [],
        "average_volume": 0.0,
        "benchmark_candles": [],
        "orderbook": None,
        "risk_state": None,
        "market_data_healthy": True,
        "broker_healthy": True,
        "position_already_open": False,
    }
    defaults.update(overrides)
    return RevalidationInput(**defaults)  # type: ignore[arg-type]


def test_expired_short_circuits_everything_else() -> None:
    data = _base_input(approval_expires_at=NOW - timedelta(seconds=1), market_data_healthy=False)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.EXPIRED
    assert report.reasons == ["approval TTL elapsed"]


def test_valid_when_everything_checks_out() -> None:
    data = _base_input(current_price=4010.0)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.VALID
    assert report.reasons == []


def test_invalidated_when_price_already_hit_stop() -> None:
    data = _base_input(current_price=3850.0)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert any("stop" in r for r in report.reasons)


def test_invalidated_when_entry_has_drifted_too_far() -> None:
    # entry_high=4020, +5% is way past the default 0.5% max drift.
    data = _base_input(current_price=4020.0 * 1.05)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert any("drifted" in r for r in report.reasons)


def test_valid_within_drift_tolerance() -> None:
    data = _base_input(current_price=4020.0 * 1.001)  # 0.1% past entry_high
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.VALID


def test_invalidated_when_market_data_unhealthy() -> None:
    data = _base_input(market_data_healthy=False)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert "market data feed is unhealthy" in report.reasons


def test_invalidated_when_broker_unhealthy() -> None:
    data = _base_input(broker_healthy=False)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert "execution broker is unhealthy" in report.reasons


def test_invalidated_when_position_already_open() -> None:
    data = _base_input(position_already_open=True)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert "a position in this symbol is already open" in report.reasons


def test_invalidated_when_kill_switch_active() -> None:
    risk_state = RiskState(
        as_of=NOW,
        daily_loss=0,
        daily_loss_limit=100000,
        exposure=0,
        exposure_limit=500000,
        open_positions=0,
        max_positions=5,
        consecutive_stops=0,
        kill_switch_active=True,
        kill_switch_reason="daily loss limit hit",
    )
    data = _base_input(risk_state=risk_state)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert any("kill switch" in r for r in report.reasons)


def test_invalidated_when_exposure_limit_would_be_exceeded() -> None:
    risk_state = RiskState(
        as_of=NOW,
        daily_loss=0,
        daily_loss_limit=100000,
        exposure=600000,
        exposure_limit=500000,
        open_positions=1,
        max_positions=5,
        consecutive_stops=0,
    )
    data = _base_input(risk_state=risk_state)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert "portfolio exposure limit would be exceeded" in report.reasons


def test_invalidated_when_daily_loss_limit_would_be_exceeded() -> None:
    risk_state = RiskState(
        as_of=NOW,
        daily_loss=150000,
        daily_loss_limit=100000,
        exposure=0,
        exposure_limit=500000,
        open_positions=0,
        max_positions=5,
        consecutive_stops=0,
    )
    data = _base_input(risk_state=risk_state)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert "daily loss limit would be exceeded" in report.reasons


def test_invalidated_when_rvol_dropped_below_threshold() -> None:
    candles = [_candle(4010.0, volume=50, minute=0)]
    data = _base_input(recent_candles=candles, average_volume=100.0)
    report = revalidate(data, thresholds=RevalidationThresholds(min_rvol=1.0))
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert any("RVOL" in r for r in report.reasons)


def test_valid_when_rvol_still_above_threshold() -> None:
    candles = [_candle(4010.0, volume=150, minute=0)]
    data = _base_input(recent_candles=candles, average_volume=100.0)
    report = revalidate(data, thresholds=RevalidationThresholds(min_rvol=1.0))
    assert report.verdict == RevalidationVerdict.VALID


def test_invalidated_when_spread_too_wide() -> None:
    orderbook = OrderBook(
        symbol="KRW-XRP",
        bids=[OrderBookLevel(price=3950.0, quantity=10)],
        asks=[OrderBookLevel(price=4070.0, quantity=10)],  # ~3% spread
        exchange_ts=NOW,
        received_ts=NOW,
    )
    data = _base_input(orderbook=orderbook)
    report = revalidate(data, thresholds=RevalidationThresholds(max_spread_pct=0.5))
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert any("spread" in r for r in report.reasons)


def test_invalidated_when_slippage_too_high() -> None:
    # Thin book: only 1 unit available at the best ask, expected_max_loss
    # implies a much larger quantity, so the walk pushes the average price
    # far past the best ask.
    orderbook = OrderBook(
        symbol="KRW-XRP",
        bids=[OrderBookLevel(price=4005.0, quantity=100)],
        asks=[
            OrderBookLevel(price=4010.0, quantity=1),
            OrderBookLevel(price=4500.0, quantity=1000),
        ],
        exchange_ts=NOW,
        received_ts=NOW,
    )
    data = _base_input(orderbook=orderbook)
    report = revalidate(data, thresholds=RevalidationThresholds(max_spread_pct=100.0, max_slippage_pct=1.0))
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert any("slippage" in r for r in report.reasons)


def test_invalidated_when_regime_turns_risk_off() -> None:
    # A steadily falling benchmark: below its MA and the MA itself falling.
    benchmark = [_candle(1000.0 - i, minute=i) for i in range(25)]
    data = _base_input(benchmark_candles=benchmark)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert any("RISK_OFF" in r for r in report.reasons)


def test_valid_when_regime_is_risk_on() -> None:
    benchmark = [_candle(1000.0 + i, minute=i) for i in range(25)]
    data = _base_input(benchmark_candles=benchmark)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.VALID


def test_invalidated_when_ensemble_score_turns_bearish() -> None:
    # A relentless downtrend: RSI low, MACD histogram negative, both
    # strategies SHORT -> ensemble score well below 0.
    candles = [_candle(5000.0 - i * 10, minute=i) for i in range(40)]
    data = _base_input(recent_candles=candles, current_price=candles[-1].close + 1)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert any("ensemble score" in r for r in report.reasons)


def test_multiple_reasons_all_reported_together() -> None:
    data = _base_input(market_data_healthy=False, broker_healthy=False, position_already_open=True)
    report = revalidate(data)
    assert report.verdict == RevalidationVerdict.INVALIDATED
    assert len(report.reasons) == 3
