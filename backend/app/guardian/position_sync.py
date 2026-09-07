"""Position sync / mismatch detection (P16).

Compares this system's own `Position` rows against what the broker reports
holding, to catch the classic failure modes docs/MASTER_SPEC.md's Final
Instruction calls out ("if... position state is uncertain, block new
trades"): a quantity drift, a position we think is open that the broker has
no record of, or a broker holding we have no local record of at all (e.g. a
fill from a manual/out-of-band trade, or a local row lost to a bug).

Pure function over an already-normalized `BrokerHolding` list rather than a
specific broker's raw payload shape - Toss's/Upbit's holdings response
fields aren't fully verified yet (see docs/TOSS_SETUP.md, docs/UPBIT_NOTES.md),
so the caller maps whichever broker's real response into this shape rather
than this module guessing at unconfirmed field names.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.db.models import Position

_DEFAULT_QUANTITY_TOLERANCE = 1e-6


class MismatchKind(str, Enum):
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    MISSING_AT_BROKER = "MISSING_AT_BROKER"
    MISSING_LOCALLY = "MISSING_LOCALLY"


@dataclass
class BrokerHolding:
    symbol: str
    quantity: float


@dataclass
class PositionMismatch:
    symbol: str
    kind: MismatchKind
    local_quantity: float | None
    broker_quantity: float | None


def find_position_mismatches(
    local_positions: list[Position],
    broker_holdings: list[BrokerHolding],
    quantity_tolerance: float = _DEFAULT_QUANTITY_TOLERANCE,
) -> list[PositionMismatch]:
    local_by_symbol = {p.symbol: p for p in local_positions if p.quantity > 0}
    broker_by_symbol = {h.symbol: h for h in broker_holdings if h.quantity > 0}

    mismatches: list[PositionMismatch] = []

    for symbol, position in local_by_symbol.items():
        holding = broker_by_symbol.get(symbol)
        if holding is None:
            mismatches.append(
                PositionMismatch(symbol, MismatchKind.MISSING_AT_BROKER, position.quantity, None)
            )
        elif abs(position.quantity - holding.quantity) > quantity_tolerance:
            mismatches.append(
                PositionMismatch(symbol, MismatchKind.QUANTITY_MISMATCH, position.quantity, holding.quantity)
            )

    for symbol, holding in broker_by_symbol.items():
        if symbol not in local_by_symbol:
            mismatches.append(
                PositionMismatch(symbol, MismatchKind.MISSING_LOCALLY, None, holding.quantity)
            )

    return mismatches
