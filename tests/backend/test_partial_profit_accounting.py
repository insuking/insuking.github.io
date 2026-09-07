from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import TradePlan
from app.models.domain import PositionState
from app.partial_profit.accounting import FillEvent, compute_position_accounting

pytestmark = pytest.mark.P17

NOW = datetime(2026, 1, 5, tzinfo=UTC)


def _trade_plan(**overrides: object) -> TradePlan:
    defaults: dict[str, object] = {
        "id": "plan-1",
        "approval_id": "appr-1",
        "symbol": "KRW-XRP",
        "initial_qty": 100.0,
        "t1_percent": 30.0,
        "t2_percent": 30.0,
        "runner_percent": 40.0,
        "entry_price": 100.0,
        "stop_price": 90.0,
        "t1_price": 110.0,
        "t2_price": 120.0,
    }
    defaults.update(overrides)
    return TradePlan(**defaults)


def _fill(side: str, quantity: float, price: float, minute: int = 0) -> FillEvent:
    return FillEvent(side=side, quantity=quantity, price=price, filled_at=NOW + timedelta(minutes=minute))


def test_no_fills_is_open_with_zero_everything() -> None:
    result = compute_position_accounting(_trade_plan(), [])
    assert result.state == PositionState.OPEN
    assert result.filled_entry_qty == 0
    assert result.remaining_qty == 0
    assert result.avg_entry_price == 0
    assert result.realized_pnl == 0


def test_entry_fill_only_is_open() -> None:
    fills = [_fill("BUY", 100, 100)]
    result = compute_position_accounting(_trade_plan(), fills)

    assert result.state == PositionState.OPEN
    assert result.filled_entry_qty == 100
    assert result.remaining_qty == 100
    assert result.avg_entry_price == 100


def test_weighted_average_entry_price_across_multiple_buys() -> None:
    fills = [_fill("BUY", 50, 100, minute=0), _fill("BUY", 50, 110, minute=1)]
    result = compute_position_accounting(_trade_plan(), fills)

    assert result.avg_entry_price == pytest.approx(105.0)
    assert result.filled_entry_qty == 100


def test_partial_t1_fill_does_not_advance_state() -> None:
    """The core 'never assumed requested fill' behavior: a T1 sell order
    for 30 units that only partially filled (15 of 30) must NOT be treated
    as T1_FILLED."""
    fills = [_fill("BUY", 100, 100, minute=0), _fill("SELL", 15, 110, minute=1)]
    result = compute_position_accounting(_trade_plan(), fills)

    assert result.state == PositionState.OPEN
    assert result.remaining_qty == 85
    assert result.realized_pnl == pytest.approx((110 - 100) * 15)


def test_full_t1_fill_advances_to_t1_filled() -> None:
    fills = [_fill("BUY", 100, 100, minute=0), _fill("SELL", 30, 110, minute=1)]
    result = compute_position_accounting(_trade_plan(), fills)

    assert result.state == PositionState.T1_FILLED
    assert result.remaining_qty == 70
    assert result.realized_pnl == pytest.approx((110 - 100) * 30)


def test_partial_t2_fill_after_t1_stays_t1_filled() -> None:
    fills = [
        _fill("BUY", 100, 100, minute=0),
        _fill("SELL", 30, 110, minute=1),
        _fill("SELL", 10, 120, minute=2),  # only 10 of the intended 30 for T2
    ]
    result = compute_position_accounting(_trade_plan(), fills)

    assert result.state == PositionState.T1_FILLED
    assert result.remaining_qty == 60


def test_full_t1_and_t2_fills_advance_to_runner() -> None:
    fills = [
        _fill("BUY", 100, 100, minute=0),
        _fill("SELL", 30, 110, minute=1),
        _fill("SELL", 30, 120, minute=2),
    ]
    result = compute_position_accounting(_trade_plan(), fills)

    assert result.state == PositionState.RUNNER
    assert result.remaining_qty == 40
    assert result.realized_pnl == pytest.approx((110 - 100) * 30 + (120 - 100) * 30)


def test_full_exit_closes_the_position() -> None:
    fills = [_fill("BUY", 100, 100, minute=0), _fill("SELL", 100, 130, minute=1)]
    result = compute_position_accounting(_trade_plan(), fills)

    assert result.state == PositionState.CLOSED
    assert result.remaining_qty == 0
    assert result.realized_pnl == pytest.approx((130 - 100) * 100)


def test_stop_out_before_any_target_still_closes_from_open() -> None:
    fills = [_fill("BUY", 100, 100, minute=0), _fill("SELL", 100, 90, minute=1)]
    result = compute_position_accounting(_trade_plan(), fills)

    assert result.state == PositionState.CLOSED
    assert result.realized_pnl == pytest.approx((90 - 100) * 100)


def test_overselling_never_goes_negative() -> None:
    # A data-integrity edge case (exit fills exceeding entry fills) - must
    # clamp rather than report a nonsensical negative remaining quantity.
    fills = [_fill("BUY", 50, 100, minute=0), _fill("SELL", 60, 110, minute=1)]
    result = compute_position_accounting(_trade_plan(), fills)

    assert result.remaining_qty == 0
    assert result.state == PositionState.CLOSED


def test_custom_percent_split_changes_thresholds() -> None:
    plan = _trade_plan(t1_percent=20.0, t2_percent=50.0, runner_percent=30.0)
    # t1_threshold = 20, t2_threshold = 70
    fills = [_fill("BUY", 100, 100, minute=0), _fill("SELL", 20, 110, minute=1)]
    result = compute_position_accounting(plan, fills)
    assert result.state == PositionState.T1_FILLED

    fills_full = fills + [_fill("SELL", 50, 120, minute=2)]
    result_full = compute_position_accounting(plan, fills_full)
    assert result_full.state == PositionState.RUNNER
    assert result_full.remaining_qty == 30
