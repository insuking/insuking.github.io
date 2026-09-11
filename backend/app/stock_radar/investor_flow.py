"""P25: Stealth Accumulation - foreign/institutional net-flow signal.

KIS's `inquire-investor` endpoint (tr_id `FHKST01010900`, see
`KisRestClient.get_investor_trend()`) is the data source: daily foreign
(외국인) and institutional (기관) net-buy share counts per symbol. The
master spec's 100-point table groups this under "외국인/기관/프로그램 수급"
(19pt) alongside program-trading (프로그램) net flow - this phase only
implements the foreign+institutional two-thirds of that. KIS's
program-trading feed is a separate endpoint this project hasn't touched
yet, so it stays a documented, honest gap - same as P23's own 35-point gap
before P25 started closing it. See `scoring.py`'s `institutional_flow`
weight (12.0 of the spec's 19) for how that partial coverage is reflected
in the score rather than claimed as the full category.

Pure functions only, same split as `app/radar/features.py` - no I/O here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class InvestorFlowBar:
    date: datetime
    foreign_net_qty: float
    institution_net_qty: float


def net_buy_day_ratio(bars: list[InvestorFlowBar], window: int = 10) -> float | None:
    """Fraction (0.0-1.0) of the last `window` trading days where combined
    foreign+institutional net flow was positive (net buying) - "stealth
    accumulation": sustained buying pressure from these two investor
    classes, which can build before price actually breaks out. A simple,
    honest day-count ratio rather than a magnitude-weighted score, since
    KIS's net-buy quantity isn't normalized against a stock's own typical
    volume the way `app/radar/features.py`'s other signals are - counting
    net-buy days avoids implicitly comparing raw share counts across very
    differently sized stocks. `None` without enough history, never a
    fabricated value.
    """
    if len(bars) < window:
        return None
    recent = bars[-window:]
    buy_days = sum(1 for b in recent if (b.foreign_net_qty + b.institution_net_qty) > 0)
    return buy_days / window
