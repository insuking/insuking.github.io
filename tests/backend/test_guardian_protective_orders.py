import pytest

from app.db.models import TradePlan
from app.guardian.protective_orders import (
    initial_protective_orders,
    next_stop_after_t1,
    runner_quantity,
)

pytestmark = pytest.mark.P16


def _trade_plan(**overrides: object) -> TradePlan:
    defaults: dict[str, object] = {
        "id": "plan-1",
        "approval_id": "appr-1",
        "symbol": "KRW-XRP",
        "initial_qty": 100.0,
        "t1_percent": 30.0,
        "t2_percent": 30.0,
        "runner_percent": 40.0,
        "entry_price": 4000.0,
        "stop_price": 3900.0,
        "t1_price": 4100.0,
        "t2_price": 4200.0,
    }
    defaults.update(overrides)
    return TradePlan(**defaults)


def test_initial_protective_orders_sizes_legs_by_percent() -> None:
    plan = _trade_plan()
    specs = initial_protective_orders(plan)

    by_kind = {spec.kind: spec for spec in specs}
    assert by_kind["STOP"].trigger_price == 3900.0
    assert by_kind["STOP"].quantity == 100.0
    assert by_kind["T1"].trigger_price == 4100.0
    assert by_kind["T1"].quantity == pytest.approx(30.0)
    assert by_kind["T2"].trigger_price == 4200.0
    assert by_kind["T2"].quantity == pytest.approx(30.0)


def test_runner_quantity_is_remaining_percent() -> None:
    plan = _trade_plan(initial_qty=200.0, runner_percent=40.0)
    assert runner_quantity(plan) == pytest.approx(80.0)


def test_next_stop_after_t1_moves_to_breakeven() -> None:
    plan = _trade_plan(entry_price=4000.0)
    assert next_stop_after_t1(plan, current_stop_price=3900.0) == 4000.0


def test_next_stop_after_t1_never_loosens_when_current_stop_is_already_tighter() -> None:
    plan = _trade_plan(entry_price=4000.0)
    # Some prior trailing update already pushed the stop above breakeven -
    # moving "to breakeven" here must not drag it back down.
    assert next_stop_after_t1(plan, current_stop_price=4050.0) == 4050.0
