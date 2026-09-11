"""Turn a P27 CONFIRMED entry into a real P1 `Recommendation` (P31).

The gap this closes: `app/recommendation/engine.py`'s `build_recommendation()`
was built for the crypto radar's intraday opening-range model (P4/P9) - it
needs `breakout_level`/`structural_stop`/`rvol`/`clv` computed from minute
candles, none of which the stock radar (P23/P25/P26/P27) computes, since it
scores from *daily* candles through an entirely different signal set
(compression/OBV/distance-to-high/institutional-flow, see
`app/stock_radar/scoring.py`). Forcing a `PreBreakoutScore` through the
crypto-shaped `build_recommendation()` would mean inventing RVOL/relative-
strength numbers this module never computed, and replacing the already-
tuned PRE-BREAKOUT score with a differently-weighted one. Until now nothing
did either - a CONFIRMED verdict from `scripts/reconfirm_entries.py` was
printed and thrown away, never persisted as a `Recommendation`, so the
"추천" tab and Home's "TOP 추천" never showed a stock candidate no matter
how the radar scored it.

This function stays stock-appropriate instead: the PRE-BREAKOUT score
(already a real, tested 0-77/65-point signal) is rescaled to the domain
`Recommendation.score`'s 0-100 range rather than replaced; `reasons`/
`risks` reuse the same `ScoreFactor.detail` strings the 종목레이더 tab
already shows, not fabricated new text; entry uses the real reconfirmed
quote (`EntryConfirmation.current_price`, P27); and the stop is an
ATR-multiple below entry - the same `atr_multiplier=2.0`/`atr_window=14`
default `app/guardian/trailing.py` already uses for trailing stops, reused
here rather than inventing a second stop convention, computed from real
daily candles via P10's already-tested `atr()`. T1/T2 R-multiples,
percentages, risk-per-trade, and TTL are `app/recommendation/engine.py`'s
own existing defaults, reused directly for one consistent risk model
across both the crypto and stock recommendation paths.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.domain import AssetType, Candle, Recommendation
from app.recommendation.engine import (
    DEFAULT_RISK_PER_TRADE,
    DEFAULT_RUNNER_PERCENT,
    DEFAULT_T1_PERCENT,
    DEFAULT_T1_R_MULTIPLE,
    DEFAULT_T2_PERCENT,
    DEFAULT_T2_R_MULTIPLE,
    DEFAULT_TTL_SECONDS,
    position_size,
)
from app.stock_radar.entry_confirmation import EntryConfirmation, EntryVerdict
from app.stock_radar.scoring import PreBreakoutScore
from app.technical.indicators import atr

# Matches app/guardian/trailing.py's trailing_stop_price() defaults exactly
# - same ATR-multiple-below-close convention, reused for the *initial*
# stop here rather than invented separately.
DEFAULT_ATR_WINDOW = 14
DEFAULT_ATR_STOP_MULTIPLE = 2.0

_DEFAULT_FALLBACK_REASON = "가격 압축 및 거래량 신호 기반 돌파 후보"
_DEFAULT_FALLBACK_RISK = "일반적인 돌파 리스크: 돌파 이후 되돌림(실패한 돌파) 가능성"


def build_stock_recommendation(
    score: PreBreakoutScore,
    confirmation: EntryConfirmation,
    recent_candles: list[Candle],
    account_buying_power: float,
    name: str | None = None,
    atr_window: int = DEFAULT_ATR_WINDOW,
    atr_stop_multiple: float = DEFAULT_ATR_STOP_MULTIPLE,
    risk_per_trade: float = DEFAULT_RISK_PER_TRADE,
    t1_r_multiple: float = DEFAULT_T1_R_MULTIPLE,
    t2_r_multiple: float = DEFAULT_T2_R_MULTIPLE,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> Recommendation | None:
    """Returns `None` - never a fabricated recommendation - when:
    `confirmation` isn't CONFIRMED; `recent_candles` doesn't cover
    `atr_window` real bars yet; or the resulting stop isn't strictly below
    entry (an invalid or degenerate risk setup) - same never-fabricate
    gating `app.recommendation.engine.build_recommendation()` already uses.
    `name` (P33): the KOSPI/KOSDAQ Korean company name for display (e.g.
    "삼성전자") - already known by the time a symbol is CONFIRMED (KIS
    returned it during the original scan, see `scan_stock_universe()`'s
    `names` dict), threaded through here rather than re-fetched.
    """
    if confirmation.verdict != EntryVerdict.CONFIRMED:
        return None
    if confirmation.symbol != score.symbol:
        raise ValueError(f"score/confirmation symbol mismatch: {score.symbol!r} vs {confirmation.symbol!r}")

    atr_values = atr(recent_candles, window=atr_window)
    if not atr_values or atr_values[-1] is None:
        return None
    latest_atr = atr_values[-1]

    entry_low = confirmation.current_price
    if entry_low <= 0:
        return None
    entry_high = entry_low * 1.005
    stop_price = entry_low - atr_stop_multiple * latest_atr
    if stop_price <= 0:
        return None

    r = entry_low - stop_price
    if r <= 0:
        return None

    t1_price = entry_low + r * t1_r_multiple
    t2_price = entry_low + r * t2_r_multiple

    risk_amount = account_buying_power * risk_per_trade
    quantity = position_size(risk_amount, entry_low, stop_price)
    expected_max_loss = quantity * r
    risk_reward = (t2_price - entry_low) / r

    normalized_score = (score.total_score / score.max_available * 100) if score.max_available > 0 else 0.0
    normalized_score = min(max(normalized_score, 0.0), 100.0)

    reasons = [f.detail for f in score.positive] or [_DEFAULT_FALLBACK_REASON]
    risks = [f.detail for f in score.negative] or [_DEFAULT_FALLBACK_RISK]

    resolved_now = now or datetime.now(UTC)
    return Recommendation(
        id=f"stock-radar-{score.symbol}",
        symbol=score.symbol,
        name=name,
        asset_type=AssetType.STOCK,
        score=round(normalized_score, 1),
        state="CONFIRMED_BREAKOUT",
        entry_low=entry_low,
        entry_high=entry_high,
        stop_price=stop_price,
        t1_price=t1_price,
        t1_percent=DEFAULT_T1_PERCENT,
        t2_price=t2_price,
        t2_percent=DEFAULT_T2_PERCENT,
        runner_percent=DEFAULT_RUNNER_PERCENT,
        expected_max_loss=expected_max_loss,
        risk_reward=risk_reward,
        reasons=reasons,
        risks=risks,
        created_at=resolved_now,
        expires_at=resolved_now + timedelta(seconds=ttl_seconds),
    )
