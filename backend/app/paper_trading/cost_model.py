"""Transaction cost model (P20).

Paper trading is only useful if its PnL reflects what a real fill would
have actually cost - docs/MASTER_SPEC.md's P20 bullet calls out fees, tax,
spread, and slippage by name. This module covers the two cost components
that depend only on notional value and side (commission + tax); spread and
slippage are priced into the fill itself by `fill_simulator.py`.

The rates below are configurable defaults, not authoritative tax/fee
figures - Korean securities transaction tax (증권거래세) rates are set by
law and have changed multiple times in recent years, and real brokerage
commission schedules vary by broker/tier. Treat `STOCK_COSTS`/`CRYPTO_COSTS`
as a reasonable starting point for simulation, and update them to whatever
schedule is actually in effect before drawing any real conclusion from a
replay or paper-trading result.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TradingCosts:
    commission_rate: float
    """Broker commission, charged on both buy and sell notional."""

    sell_tax_rate: float
    """Transaction tax, charged on sell notional only (Korean 증권거래세
    convention for stocks; 0 for crypto - Korea has no crypto transaction
    tax in effect at the time this was written)."""


# KOSPI/KOSDAQ via Toss: illustrative ~0.015% brokerage commission plus the
# combined 증권거래세 + 농특세 sell-side tax. Update to the broker's actual
# published schedule before relying on this for real decisions.
STOCK_COSTS = TradingCosts(commission_rate=0.00015, sell_tax_rate=0.0018)

# Upbit KRW market: published taker fee is 0.05%; no sell-side tax.
CRYPTO_COSTS = TradingCosts(commission_rate=0.0005, sell_tax_rate=0.0)

_COSTS_BY_ASSET_TYPE = {"STOCK": STOCK_COSTS, "CRYPTO": CRYPTO_COSTS}


def costs_for_asset_type(asset_type: str) -> TradingCosts:
    try:
        return _COSTS_BY_ASSET_TYPE[asset_type]
    except KeyError as exc:
        raise ValueError(f"no cost model for asset_type={asset_type!r}") from exc


def calculate_commission(notional: float, costs: TradingCosts) -> float:
    return abs(notional) * costs.commission_rate


def calculate_tax(notional: float, side: str, costs: TradingCosts) -> float:
    if side != "SELL":
        return 0.0
    return abs(notional) * costs.sell_tax_rate


def total_transaction_cost(notional: float, side: str, costs: TradingCosts) -> float:
    return calculate_commission(notional, costs) + calculate_tax(notional, side, costs)
