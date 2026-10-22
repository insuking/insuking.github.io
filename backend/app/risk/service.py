"""Risk service orchestration (P18).

Evaluates the kill switch (kill_switch.py) and persists the resulting
`RiskState` snapshot (state_store.py) as one step, plus a query for "is a
new trade allowed right now" that reads back whatever was last recorded -
so a caller deciding whether to approve a new trade never has to
re-evaluate every signal itself, just ask what Risk last concluded.

Never touches Guardian's protective-order logic (app/guardian/service.py) -
see kill_switch.py's module docstring for why that boundary is load-bearing.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import RiskState
from app.risk.kill_switch import (
    DEFAULT_THRESHOLDS,
    KillSwitchReport,
    RiskContext,
    RiskThresholds,
    evaluate_kill_switch,
)
from app.risk.state_store import RiskStateRow, latest_risk_state, record_risk_state


class RiskService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def evaluate_and_record(
        self, context: RiskContext, thresholds: RiskThresholds = DEFAULT_THRESHOLDS
    ) -> tuple[RiskStateRow, KillSwitchReport]:
        report = evaluate_kill_switch(context, thresholds)
        reason = "; ".join(report.reasons) if report.reasons else None
        snapshot = RiskState(
            as_of=context.risk_state.as_of,
            daily_loss=context.risk_state.daily_loss,
            daily_loss_limit=context.risk_state.daily_loss_limit,
            exposure=context.risk_state.exposure,
            exposure_limit=context.risk_state.exposure_limit,
            open_positions=context.risk_state.open_positions,
            max_positions=context.risk_state.max_positions,
            consecutive_stops=context.risk_state.consecutive_stops,
            kill_switch_active=report.active,
            kill_switch_reason=reason,
        )
        row = await record_risk_state(self._session, snapshot)
        return row, report

    async def should_block_new_trades(self) -> bool:
        """True unless the last recorded risk state is both known and
        clear. No recorded risk state at all is treated as "uncertain, so
        block" per docs/MASTER_SPEC.md's Final Instruction, not as "assume
        fine because nothing was ever evaluated."
        """
        latest = await latest_risk_state(self._session)
        if latest is None:
            return True
        return latest.kill_switch_active
