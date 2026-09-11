"""P38: pure classification tests for app.radar.macro_regime."""

from __future__ import annotations

import pytest

from app.radar.macro_regime import MacroReading, MacroRegime, classify_macro_regime

pytestmark = pytest.mark.P38


def _reading(**overrides: float | None) -> MacroReading:
    defaults: dict[str, float | None] = {
        "sp500_change_pct": 0.1,
        "sox_change_pct": 0.1,
        "vix_level": 18.0,
        "oil_change_pct": 0.5,
        "usdkrw_change_pct": 0.1,
    }
    defaults.update(overrides)
    return MacroReading(**defaults)  # type: ignore[arg-type]


def test_all_missing_data_is_neutral_with_a_no_data_headline() -> None:
    regime, headline = classify_macro_regime(
        MacroReading(
            sp500_change_pct=None, sox_change_pct=None, vix_level=None,
            oil_change_pct=None, usdkrw_change_pct=None,
        )
    )
    assert regime is MacroRegime.NEUTRAL
    assert "데이터 없음" in headline


def test_mild_readings_with_no_trigger_are_neutral() -> None:
    regime, headline = classify_macro_regime(_reading())
    assert regime is MacroRegime.NEUTRAL
    assert "위험 신호 없음" in headline


def test_high_vix_alone_forces_risk_off() -> None:
    regime, headline = classify_macro_regime(_reading(vix_level=27.3))
    assert regime is MacroRegime.RISK_OFF
    assert "VIX 27.3" in headline


def test_sp500_sharp_decline_forces_risk_off() -> None:
    regime, headline = classify_macro_regime(_reading(sp500_change_pct=-2.0))
    assert regime is MacroRegime.RISK_OFF
    assert "S&P500" in headline


def test_sox_sharp_decline_forces_risk_off() -> None:
    regime, headline = classify_macro_regime(_reading(sox_change_pct=-3.0))
    assert regime is MacroRegime.RISK_OFF
    assert "SOX" in headline


def test_oil_spike_either_direction_forces_risk_off() -> None:
    up_regime, _ = classify_macro_regime(_reading(oil_change_pct=5.0))
    down_regime, _ = classify_macro_regime(_reading(oil_change_pct=-5.0))
    assert up_regime is MacroRegime.RISK_OFF
    assert down_regime is MacroRegime.RISK_OFF


def test_krw_weakening_forces_risk_off() -> None:
    regime, headline = classify_macro_regime(_reading(usdkrw_change_pct=1.5))
    assert regime is MacroRegime.RISK_OFF
    assert "원/달러" in headline


def test_multiple_triggers_are_all_listed_in_the_headline() -> None:
    regime, headline = classify_macro_regime(_reading(vix_level=30.0, sp500_change_pct=-2.5))
    assert regime is MacroRegime.RISK_OFF
    assert "VIX" in headline
    assert "S&P500" in headline


def test_all_supportive_signals_together_are_risk_on() -> None:
    regime, headline = classify_macro_regime(
        _reading(vix_level=12.0, sp500_change_pct=1.0, sox_change_pct=1.2)
    )
    assert regime is MacroRegime.RISK_ON
    assert "우호적" in headline


def test_partial_supportive_signals_are_not_enough_for_risk_on() -> None:
    # VIX low and S&P up, but SOX missing - not enough to declare RISK_ON.
    regime, _ = classify_macro_regime(
        _reading(vix_level=12.0, sp500_change_pct=1.0, sox_change_pct=None)
    )
    assert regime is not MacroRegime.RISK_ON


def test_missing_data_never_counts_as_a_trigger() -> None:
    # Only VIX data available and it's calm - should not spuriously
    # trigger RISK_OFF just because other fields are None.
    regime, _ = classify_macro_regime(
        MacroReading(
            sp500_change_pct=None, sox_change_pct=None, vix_level=10.0,
            oil_change_pct=None, usdkrw_change_pct=None,
        )
    )
    assert regime is not MacroRegime.RISK_OFF
