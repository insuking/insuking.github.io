"""Partial profit accounting engine (P17).

Per docs/MASTER_SPEC.md: "TradePlan with initial_qty/t1_percent/t2_percent/
runner_percent (default 30/30/40), state derived from actual fills, never
assumed requested fill." A `TradePlan` (P2) records what was *intended* -
submitting a T1 sell order for 30% of the position does not mean 30% has
actually sold; this module only ever looks at `FillEvent`s (what actually
happened) to derive quantity, average entry price, realized P&L, and
`PositionState`.

State derivation is threshold-based on cumulative sold quantity, not on
which specific order a fill came from (this codebase has no reliable way to
tag a fill as "the T1 order" vs. "the T2 order" - see
app/guardian/protective_orders.py's `ProtectiveOrderSpec`, which computes
intended sizes but isn't itself fill-tracked). A partial T1 fill - say 15 of
30 intended units - keeps the position `OPEN`, not `T1_FILLED`, until the
cumulative sold quantity actually crosses the T1 threshold: exactly the
"never assumed requested fill" rule.

`RUNNER` is reached directly once cumulative sold crosses the T2 threshold
with quantity still remaining - `T2_FILLED` is deliberately not a state
this module produces on its own: distinguishing "the instant T2 completed"
from "now holding the runner" needs an event log this snapshot-style
function doesn't have, and guessing at that distinction would be exactly
the kind of unverified behavior this project avoids. See
app/guardian/service.py for the Guardian-side operational states that build
on top of whatever this module derives.

Uses weighted-average-cost accounting (not FIFO) for realized P&L - the
standard, simplest model for a single entry-then-scale-out position like
this one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.db.models import TradePlan
from app.models.domain import PositionState

_DEFAULT_QUANTITY_TOLERANCE = 1e-9


@dataclass
class FillEvent:
    side: str  # "BUY" | "SELL"
    quantity: float
    price: float
    filled_at: datetime


@dataclass
class PositionAccounting:
    filled_entry_qty: float
    filled_exit_qty: float
    remaining_qty: float
    avg_entry_price: float
    realized_pnl: float
    state: PositionState


def compute_position_accounting(
    trade_plan: TradePlan,
    fills: list[FillEvent],
    quantity_tolerance: float = _DEFAULT_QUANTITY_TOLERANCE,
) -> PositionAccounting:
    buys = [f for f in fills if f.side == "BUY"]
    sells = [f for f in fills if f.side == "SELL"]

    filled_entry_qty = sum(f.quantity for f in buys)
    filled_exit_qty = sum(f.quantity for f in sells)
    # Never goes negative even if exit fills somehow exceed entry fills (a
    # data-integrity problem this module can't fix, only avoid amplifying).
    remaining_qty = max(0.0, filled_entry_qty - filled_exit_qty)

    avg_entry_price = (
        sum(f.quantity * f.price for f in buys) / filled_entry_qty if filled_entry_qty > 0 else 0.0
    )
    realized_pnl = sum((f.price - avg_entry_price) * f.quantity for f in sells)

    t1_threshold = trade_plan.initial_qty * trade_plan.t1_percent / 100
    t2_threshold = t1_threshold + trade_plan.initial_qty * trade_plan.t2_percent / 100

    if filled_entry_qty <= quantity_tolerance:
        state = PositionState.OPEN
    elif remaining_qty <= quantity_tolerance:
        state = PositionState.CLOSED
    elif filled_exit_qty >= t2_threshold - quantity_tolerance:
        state = PositionState.RUNNER
    elif filled_exit_qty >= t1_threshold - quantity_tolerance:
        state = PositionState.T1_FILLED
    else:
        state = PositionState.OPEN

    return PositionAccounting(
        filled_entry_qty=filled_entry_qty,
        filled_exit_qty=filled_exit_qty,
        remaining_qty=remaining_qty,
        avg_entry_price=avg_entry_price,
        realized_pnl=realized_pnl,
        state=state,
    )
