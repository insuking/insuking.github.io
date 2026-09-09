"""P27: Overnight Re-ranking & Entry Confirmation.

A PRE-BREAKOUT score (P23) is computed from the previous trading day's
close. By the time a human would act on it, real minutes-to-hours have
passed - the price may have already gapped away from where the setup was
scored, or the broader market may have turned. This is the "진입필터"
(entry filter) the master spec places between a scored candidate and a
user's approval: not a second opinion on whether the setup was good, but
"is it still the same setup, right now".

Pure decision logic only (this file) - same split as P14's
`app/approval/revalidation.py`: a typed input bundle in, a typed verdict
out, no I/O. The thin async wrapper that fetches a fresh quote per symbol
lives in `app/stock_radar/scan.py`'s `reconfirm_candidates()`, and
`scripts/reconfirm_entries.py` is the real-market entrypoint - unlike
every other real-connection check in this project, this one genuinely
cannot be verified outside real KRX trading hours (a quote fetched
overnight or on a closed market isn't "confirming against a fresh price",
it's re-reading the same stale one), so its own docstring says so plainly
rather than pretending a sandbox run proves anything.

Gap thresholds below are this project's own conservative starting points,
not numbers pulled from any KIS documentation or the master spec's own
text (which this session no longer has verbatim) - tune them from real
morning runs once there's evidence to tune from, the same "don't invent a
number, then correct it from a real signal" discipline already used for
`DEFAULT_MAX_REQUESTS_PER_SECOND` in `rest_client.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.radar.regime import MarketRegime
from app.stock_radar.scoring import PreBreakoutScore


class EntryVerdict(str, Enum):
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class EntryConfirmationThresholds:
    """`max_gap_up_pct`: above this, the entry has already run past where
    the setup was scored - acting on it now is chasing (추격매수), which
    the master spec's philosophy explicitly warns against throughout, not
    a disciplined entry off yesterday's compression/volume signal.
    `max_gap_down_pct`: below this (a gap down), the structural thesis the
    score was built on - compression near a level, support holding - is
    presumptively broken; scoring it again from scratch tomorrow is more
    honest than re-using a stale score against a materially lower price.
    """

    max_gap_up_pct: float = 3.0
    max_gap_down_pct: float = 4.0


DEFAULT_THRESHOLDS = EntryConfirmationThresholds()


@dataclass
class EntryConfirmation:
    symbol: str
    verdict: EntryVerdict
    gap_pct: float
    reasons: list[str] = field(default_factory=list)


def confirm_entry(
    score: PreBreakoutScore,
    current_price: float,
    regime: MarketRegime,
    thresholds: EntryConfirmationThresholds = DEFAULT_THRESHOLDS,
) -> EntryConfirmation:
    """`current_price`: a real, freshly-fetched quote (see this module's
    docstring - a stale quote makes this check meaningless, not just
    inaccurate). `gap_pct` is signed: positive means the price has moved
    up from `score.reference_close`, negative means down.
    """
    if score.reference_close <= 0:
        return EntryConfirmation(
            symbol=score.symbol,
            verdict=EntryVerdict.REJECTED,
            gap_pct=0.0,
            reasons=["reference_close is not a valid price - cannot measure a gap"],
        )

    gap_pct = (current_price - score.reference_close) / score.reference_close * 100
    reasons: list[str] = []

    if gap_pct > thresholds.max_gap_up_pct:
        reasons.append(f"이미 {gap_pct:.1f}% 갭업 - 추격매수 위험 (허용 {thresholds.max_gap_up_pct}%)")
    elif gap_pct < -thresholds.max_gap_down_pct:
        reasons.append(f"{gap_pct:.1f}% 갭다운 - 전일 스코어의 구조적 근거 훼손 (허용 -{thresholds.max_gap_down_pct}%)")

    if regime == MarketRegime.RISK_OFF:
        reasons.append("시장 국면이 RISK_OFF로 전환 - 신규 진입 보류")

    verdict = EntryVerdict.REJECTED if reasons else EntryVerdict.CONFIRMED
    return EntryConfirmation(symbol=score.symbol, verdict=verdict, gap_pct=gap_pct, reasons=reasons)
