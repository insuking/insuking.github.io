from datetime import UTC, datetime

import pytest

from app.models.domain import RiskState
from app.risk.kill_switch import (
    RiskContext,
    RiskThresholds,
    evaluate_kill_switch,
    exceeds_risk_per_trade,
)

pytestmark = pytest.mark.P18

NOW = datetime(2026, 1, 5, tzinfo=UTC)


def _risk_state(**overrides: object) -> RiskState:
    defaults: dict[str, object] = {
        "as_of": NOW,
        "daily_loss": 0.0,
        "daily_loss_limit": 100000.0,
        "exposure": 0.0,
        "exposure_limit": 500000.0,
        "open_positions": 0,
        "max_positions": 5,
        "consecutive_stops": 0,
    }
    defaults.update(overrides)
    return RiskState(**defaults)  # type: ignore[arg-type]


def test_clean_state_is_not_blocked() -> None:
    report = evaluate_kill_switch(RiskContext(risk_state=_risk_state()))
    assert report.active is False
    assert report.reasons == []


def test_already_active_kill_switch_stays_active() -> None:
    rs = _risk_state(kill_switch_active=True, kill_switch_reason="manual stop")
    report = evaluate_kill_switch(RiskContext(risk_state=rs))
    assert report.active is True
    assert any("manual stop" in r for r in report.reasons)


def test_exposure_over_limit_triggers() -> None:
    rs = _risk_state(exposure=600000.0, exposure_limit=500000.0)
    report = evaluate_kill_switch(RiskContext(risk_state=rs))
    assert report.active is True
    assert any("exposure" in r for r in report.reasons)


def test_open_positions_at_max_triggers() -> None:
    rs = _risk_state(open_positions=5, max_positions=5)
    report = evaluate_kill_switch(RiskContext(risk_state=rs))
    assert report.active is True
    assert any("open positions" in r for r in report.reasons)


def test_daily_loss_over_limit_triggers() -> None:
    rs = _risk_state(daily_loss=150000.0, daily_loss_limit=100000.0)
    report = evaluate_kill_switch(RiskContext(risk_state=rs))
    assert report.active is True
    assert any("daily loss" in r for r in report.reasons)


def test_consecutive_stops_at_max_triggers() -> None:
    rs = _risk_state(consecutive_stops=3)
    report = evaluate_kill_switch(RiskContext(risk_state=rs))
    assert report.active is True
    assert any("consecutive stops" in r for r in report.reasons)


def test_consecutive_stops_below_max_does_not_trigger() -> None:
    rs = _risk_state(consecutive_stops=2)
    report = evaluate_kill_switch(RiskContext(risk_state=rs))
    assert report.active is False


def test_market_crash_triggers() -> None:
    report = evaluate_kill_switch(RiskContext(risk_state=_risk_state(), market_crash=True))
    assert report.active is True
    assert any("crash" in r for r in report.reasons)


def test_pump_risk_at_or_above_threshold_triggers() -> None:
    report = evaluate_kill_switch(RiskContext(risk_state=_risk_state(), pump_risk_score=85.0))
    assert report.active is True
    assert any("pump risk" in r for r in report.reasons)


def test_pump_risk_below_threshold_does_not_trigger() -> None:
    report = evaluate_kill_switch(RiskContext(risk_state=_risk_state(), pump_risk_score=50.0))
    assert report.active is False


def test_liquidity_slippage_over_threshold_triggers() -> None:
    report = evaluate_kill_switch(RiskContext(risk_state=_risk_state(), liquidity_slippage_pct=2.0))
    assert report.active is True
    assert any("slippage" in r for r in report.reasons)


def test_position_mismatch_triggers() -> None:
    report = evaluate_kill_switch(RiskContext(risk_state=_risk_state(), position_mismatch=True))
    assert report.active is True
    assert any("mismatch" in r for r in report.reasons)


def test_unknown_order_triggers() -> None:
    report = evaluate_kill_switch(RiskContext(risk_state=_risk_state(), unknown_order=True))
    assert report.active is True
    assert any("UNKNOWN" in r for r in report.reasons)


def test_guardian_unhealthy_triggers() -> None:
    report = evaluate_kill_switch(RiskContext(risk_state=_risk_state(), guardian_healthy=False))
    assert report.active is True
    assert any("Guardian" in r for r in report.reasons)


def test_multiple_reasons_all_reported() -> None:
    report = evaluate_kill_switch(
        RiskContext(risk_state=_risk_state(), market_crash=True, guardian_healthy=False, unknown_order=True)
    )
    assert report.active is True
    assert len(report.reasons) == 3


def test_custom_thresholds_are_respected() -> None:
    rs = _risk_state(consecutive_stops=1)
    report = evaluate_kill_switch(RiskContext(risk_state=rs), thresholds=RiskThresholds(max_consecutive_stops=1))
    assert report.active is True


# --- exceeds_risk_per_trade -------------------------------------------------


def test_exceeds_risk_per_trade_true_for_nonpositive_buying_power() -> None:
    assert exceeds_risk_per_trade(1000.0, 0.0) is True
    assert exceeds_risk_per_trade(1000.0, -100.0) is True


def test_exceeds_risk_per_trade_true_when_over_cap() -> None:
    # 2000 / 100000 = 2% > default 1% cap
    assert exceeds_risk_per_trade(2000.0, 100000.0) is True


def test_exceeds_risk_per_trade_false_when_within_cap() -> None:
    # 500 / 100000 = 0.5% <= default 1% cap
    assert exceeds_risk_per_trade(500.0, 100000.0) is False


def test_exceeds_risk_per_trade_respects_custom_threshold() -> None:
    thresholds = RiskThresholds(max_risk_per_trade_pct=5.0)
    assert exceeds_risk_per_trade(2000.0, 100000.0, thresholds) is False
