"""P20 acceptance: cost_model.py's commission/tax math - sell-only tax,
symmetric commission, and the asset-type lookup.
"""

import pytest

from app.paper_trading.cost_model import (
    CRYPTO_COSTS,
    STOCK_COSTS,
    TradingCosts,
    calculate_commission,
    calculate_tax,
    costs_for_asset_type,
    total_transaction_cost,
)

pytestmark = pytest.mark.P20

_COSTS = TradingCosts(commission_rate=0.001, sell_tax_rate=0.002)


def test_calculate_commission_applies_to_buy_and_sell_alike() -> None:
    assert calculate_commission(100_000.0, _COSTS) == pytest.approx(100.0)
    assert calculate_commission(-100_000.0, _COSTS) == pytest.approx(100.0)


def test_calculate_tax_is_zero_on_buy() -> None:
    assert calculate_tax(100_000.0, "BUY", _COSTS) == 0.0


def test_calculate_tax_applies_on_sell() -> None:
    assert calculate_tax(100_000.0, "SELL", _COSTS) == pytest.approx(200.0)


def test_total_transaction_cost_sums_commission_and_tax() -> None:
    assert total_transaction_cost(100_000.0, "SELL", _COSTS) == pytest.approx(300.0)
    assert total_transaction_cost(100_000.0, "BUY", _COSTS) == pytest.approx(100.0)


def test_costs_for_asset_type_returns_expected_models() -> None:
    assert costs_for_asset_type("STOCK") is STOCK_COSTS
    assert costs_for_asset_type("CRYPTO") is CRYPTO_COSTS


def test_costs_for_asset_type_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="no cost model"):
        costs_for_asset_type("BOND")


def test_crypto_costs_have_no_sell_tax() -> None:
    assert CRYPTO_COSTS.sell_tax_rate == 0.0
