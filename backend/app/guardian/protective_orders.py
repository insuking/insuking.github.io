"""Protective order specifications (P16).

Pure functions over a `TradePlan` (P2's persisted row - see
app/db/models.py) that compute what protective orders *should* exist for a
freshly opened position: the structural stop for the full size, plus the T1
and T2 take-profit levels sized by the plan's own percentages. Turning
these specs into rows is `PositionGuardianService.ensure_initial_orders()`
(service.py); turning them into real broker orders is a separate step this
module never takes (see service.py's module docstring for why).

Quantity/percentage bookkeeping *after* fills start happening (T1_FILLED,
T2_FILLED, runner sizing) is P17's job (docs/MASTER_SPEC.md: "Partial
profit engine... state derived from actual fills, never assumed requested
fill") - this module only computes the plan's original intent before any
fill has occurred.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.models import TradePlan


@dataclass
class ProtectiveOrderSpec:
    kind: str  # "STOP" | "T1" | "T2"
    trigger_price: float
    quantity: float


def initial_protective_orders(trade_plan: TradePlan) -> list[ProtectiveOrderSpec]:
    """The stop (full size) and the T1/T2 take-profit legs (sized by the
    plan's own percentages of `initial_qty`) - what should exist the moment
    a position opens, before any fill has happened.
    """
    total = trade_plan.initial_qty
    return [
        ProtectiveOrderSpec(kind="STOP", trigger_price=trade_plan.stop_price, quantity=total),
        ProtectiveOrderSpec(
            kind="T1", trigger_price=trade_plan.t1_price, quantity=total * trade_plan.t1_percent / 100
        ),
        ProtectiveOrderSpec(
            kind="T2", trigger_price=trade_plan.t2_price, quantity=total * trade_plan.t2_percent / 100
        ),
    ]


def runner_quantity(trade_plan: TradePlan) -> float:
    """The size expected to remain after both T1 and T2 have sold their
    shares - the position's own bookkeeping (P17) is what confirms this
    against what was *actually* filled."""
    return trade_plan.initial_qty * trade_plan.runner_percent / 100


def next_stop_after_t1(trade_plan: TradePlan, current_stop_price: float) -> float:
    """Per docs/MASTER_SPEC.md section G-J: after T1 fills, the stop may
    move to breakeven (or a structural protection level) but must never
    move below the previously allowed loss - so this always returns the
    *tighter* (higher, for a long position) of the current stop and
    breakeven, never loosening it even if breakeven happens to sit below
    the current stop.
    """
    return max(current_stop_price, trade_plan.entry_price)
