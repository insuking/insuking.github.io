from datetime import UTC, datetime

import pytest

from app.db.models import Position
from app.guardian.position_sync import BrokerHolding, MismatchKind, find_position_mismatches

pytestmark = pytest.mark.P16

NOW = datetime.now(UTC)


def _position(symbol: str, quantity: float) -> Position:
    return Position(
        id=f"pos-{symbol}",
        symbol=symbol,
        asset_type="CRYPTO",
        quantity=quantity,
        avg_entry_price=100.0,
        stop_price=90.0,
        state="OPEN",
        guardian_active=True,
        opened_at=NOW,
        updated_at=NOW,
    )


def test_no_mismatches_when_everything_agrees() -> None:
    local = [_position("KRW-XRP", 100.0)]
    broker = [BrokerHolding("KRW-XRP", 100.0)]
    assert find_position_mismatches(local, broker) == []


def test_quantity_mismatch_detected() -> None:
    local = [_position("KRW-XRP", 100.0)]
    broker = [BrokerHolding("KRW-XRP", 70.0)]

    mismatches = find_position_mismatches(local, broker)

    assert len(mismatches) == 1
    assert mismatches[0].kind == MismatchKind.QUANTITY_MISMATCH
    assert mismatches[0].local_quantity == 100.0
    assert mismatches[0].broker_quantity == 70.0


def test_missing_at_broker_detected() -> None:
    local = [_position("KRW-XRP", 100.0)]
    broker: list[BrokerHolding] = []

    mismatches = find_position_mismatches(local, broker)

    assert len(mismatches) == 1
    assert mismatches[0].kind == MismatchKind.MISSING_AT_BROKER
    assert mismatches[0].broker_quantity is None


def test_missing_locally_detected() -> None:
    local: list[Position] = []
    broker = [BrokerHolding("KRW-XRP", 50.0)]

    mismatches = find_position_mismatches(local, broker)

    assert len(mismatches) == 1
    assert mismatches[0].kind == MismatchKind.MISSING_LOCALLY
    assert mismatches[0].local_quantity is None
    assert mismatches[0].broker_quantity == 50.0


def test_zero_quantity_positions_and_holdings_are_ignored() -> None:
    local = [_position("KRW-XRP", 0.0)]
    broker = [BrokerHolding("KRW-DOGE", 0.0)]
    assert find_position_mismatches(local, broker) == []


def test_small_quantity_difference_within_tolerance_is_not_a_mismatch() -> None:
    local = [_position("KRW-XRP", 100.0)]
    broker = [BrokerHolding("KRW-XRP", 100.0000001)]
    assert find_position_mismatches(local, broker, quantity_tolerance=1e-4) == []
