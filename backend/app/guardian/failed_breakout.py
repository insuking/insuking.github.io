"""Failed-breakout exit decision (P16).

Reuses the `RadarState` vocabulary P4/P9 already track for the symbol -
`FAILED_BREAKOUT` means the breakout level that justified this trade has
already given back, which is a different (and earlier, harder) signal than
the stop price simply being hit. Only fires while the position is still in
its original `OPEN` state: once T1 has filled, the trade has already
proven itself with a partial profit, and docs/MASTER_SPEC.md's normal
stop/trailing management (not this override) governs what remains.
"""

from __future__ import annotations

from app.models.domain import PositionState
from app.radar.state import RadarState


def should_exit_on_failed_breakout(position_state: PositionState, radar_state: RadarState) -> bool:
    return radar_state == RadarState.FAILED_BREAKOUT and position_state == PositionState.OPEN
