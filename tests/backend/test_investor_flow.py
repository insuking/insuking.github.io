"""P25: stealth-accumulation investor-flow feature (pure)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.stock_radar.investor_flow import InvestorFlowBar, net_buy_day_ratio

pytestmark = pytest.mark.P25

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _bars(net_flows: list[tuple[float, float]]) -> list[InvestorFlowBar]:
    return [
        InvestorFlowBar(date=_START + timedelta(days=i), foreign_net_qty=f, institution_net_qty=o)
        for i, (f, o) in enumerate(net_flows)
    ]


def test_returns_none_without_enough_history() -> None:
    bars = _bars([(100.0, 100.0)] * 3)

    assert net_buy_day_ratio(bars, window=10) is None


def test_all_buy_days_scores_full_ratio() -> None:
    bars = _bars([(100.0, 50.0)] * 10)

    assert net_buy_day_ratio(bars, window=10) == pytest.approx(1.0)


def test_all_sell_days_scores_zero() -> None:
    bars = _bars([(-100.0, -50.0)] * 10)

    assert net_buy_day_ratio(bars, window=10) == pytest.approx(0.0)


def test_mixed_days_scores_the_buy_day_fraction() -> None:
    # 7 net-buy days (combined > 0), 3 net-sell days.
    flows = [(100.0, 50.0)] * 7 + [(-100.0, -50.0)] * 3
    bars = _bars(flows)

    assert net_buy_day_ratio(bars, window=10) == pytest.approx(0.7)


def test_a_day_where_foreign_and_institution_offset_to_zero_is_not_a_buy_day() -> None:
    flows = [(100.0, -100.0)] * 5 + [(0.0, 0.0)] * 5

    assert net_buy_day_ratio(_bars(flows), window=10) == pytest.approx(0.0)


def test_only_the_trailing_window_counts() -> None:
    # 20 sell days followed by 10 buy days - only the last 10 (all buy) should count.
    flows = [(-100.0, -50.0)] * 20 + [(100.0, 50.0)] * 10

    assert net_buy_day_ratio(_bars(flows), window=10) == pytest.approx(1.0)
