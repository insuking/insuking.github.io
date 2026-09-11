"""P38: classify the daily premarket macro snapshot (US market, SOX
semiconductor index, VIX, WTI oil, USD/KRW) into a `MacroRegime` the
시장 tab's "해외 매크로" card reads.

**Advisory only - not wired into P35/P36's automatic gating.** This
project's standing rule is that the system must never become fully
autonomous: every real-money action still requires explicit human
approval every time. Feeding an unvalidated macro threshold into P36's
automatic NO_TRADE_DAY/TOO_LATE gating would let this phase silently
block legitimate trades on thresholds nobody has backtested yet. So for
this pass, the macro reading is surfaced to the human on the 시장 탭 to
review before the day's trading - exactly how the original request
framed the 08:20 daily check-in: something a person looks at each
morning, not an automatic filter. Wiring it into `decide_entry_state()`'s
scoring is a natural next step once these thresholds have real trading
outcomes to validate against (see docs/REGIME_ADAPTIVE_RADAR.md's Known
gaps).

The thresholds below are a first, documented set of triggers, not a
tuned model - there is no backtest harness for macro thresholds yet.
Each RISK_OFF trigger fires independently (any one is enough); RISK_ON
requires every available signal to agree - the same asymmetry P34 already
uses (easy to flag caution, hard to declare "all clear").
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MacroRegime(str, Enum):
    RISK_ON = "RISK_ON"
    NEUTRAL = "NEUTRAL"
    RISK_OFF = "RISK_OFF"


@dataclass(frozen=True)
class MacroReading:
    """Any field may be `None` when that symbol's fetch failed - always
    treated as "skip this signal", never as a fabricated 0."""

    sp500_change_pct: float | None
    sox_change_pct: float | None
    vix_level: float | None
    oil_change_pct: float | None
    usdkrw_change_pct: float | None


VIX_RISK_OFF_LEVEL = 25.0
VIX_RISK_ON_LEVEL = 15.0
SP500_RISK_OFF_PCT = -1.5
SOX_RISK_OFF_PCT = -2.5
OIL_RISK_OFF_ABS_PCT = 4.0
USDKRW_RISK_OFF_PCT = 1.0  # KRW weakening (USD/KRW up) this much overnight
SP500_RISK_ON_PCT = 0.5
SOX_RISK_ON_PCT = 0.5


def classify_macro_regime(reading: MacroReading) -> tuple[MacroRegime, str]:
    """Returns `(regime, headline)` - `headline` is the one-line Korean
    reason shown on the 시장 탭, e.g. "VIX 27.3 (공포 구간, 25 이상)"."""
    if all(
        v is None
        for v in (
            reading.sp500_change_pct,
            reading.sox_change_pct,
            reading.vix_level,
            reading.oil_change_pct,
            reading.usdkrw_change_pct,
        )
    ):
        return MacroRegime.NEUTRAL, "데이터 없음 - 매크로 데이터 수집 실패"

    triggers: list[str] = []

    if reading.vix_level is not None and reading.vix_level >= VIX_RISK_OFF_LEVEL:
        triggers.append(f"VIX {reading.vix_level:.1f} (공포 구간, {VIX_RISK_OFF_LEVEL:.0f} 이상)")
    if reading.sp500_change_pct is not None and reading.sp500_change_pct <= SP500_RISK_OFF_PCT:
        triggers.append(f"S&P500 {reading.sp500_change_pct:+.1f}%")
    if reading.sox_change_pct is not None and reading.sox_change_pct <= SOX_RISK_OFF_PCT:
        triggers.append(f"필라델피아 반도체지수(SOX) {reading.sox_change_pct:+.1f}%")
    if reading.oil_change_pct is not None and abs(reading.oil_change_pct) >= OIL_RISK_OFF_ABS_PCT:
        triggers.append(f"WTI 유가 {reading.oil_change_pct:+.1f}% 급변동")
    if reading.usdkrw_change_pct is not None and reading.usdkrw_change_pct >= USDKRW_RISK_OFF_PCT:
        triggers.append(f"원/달러 환율 {reading.usdkrw_change_pct:+.1f}% (원화 약세)")

    if triggers:
        return MacroRegime.RISK_OFF, ", ".join(triggers)

    risk_on_ok = (
        reading.vix_level is not None
        and reading.vix_level <= VIX_RISK_ON_LEVEL
        and reading.sp500_change_pct is not None
        and reading.sp500_change_pct >= SP500_RISK_ON_PCT
        and reading.sox_change_pct is not None
        and reading.sox_change_pct >= SOX_RISK_ON_PCT
    )
    if risk_on_ok:
        assert reading.vix_level is not None
        assert reading.sp500_change_pct is not None
        assert reading.sox_change_pct is not None
        return MacroRegime.RISK_ON, (
            f"VIX {reading.vix_level:.1f}, S&P500 {reading.sp500_change_pct:+.1f}%, "
            f"SOX {reading.sox_change_pct:+.1f}% - 우호적"
        )

    return MacroRegime.NEUTRAL, "뚜렷한 위험 신호 없음"
