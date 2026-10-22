import pytest

from app.guardian.failed_breakout import should_exit_on_failed_breakout
from app.models.domain import PositionState
from app.radar.state import RadarState

pytestmark = pytest.mark.P16


def test_exits_when_open_and_radar_reports_failed_breakout() -> None:
    assert should_exit_on_failed_breakout(PositionState.OPEN, RadarState.FAILED_BREAKOUT) is True


def test_does_not_exit_when_radar_state_is_not_failed_breakout() -> None:
    assert should_exit_on_failed_breakout(PositionState.OPEN, RadarState.CONFIRMED_BREAKOUT) is False


@pytest.mark.parametrize(
    "state", [PositionState.T1_FILLED, PositionState.T2_FILLED, PositionState.RUNNER, PositionState.CLOSED]
)
def test_does_not_exit_once_past_open_even_on_failed_breakout(state: PositionState) -> None:
    assert should_exit_on_failed_breakout(state, RadarState.FAILED_BREAKOUT) is False
