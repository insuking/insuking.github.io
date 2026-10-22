"""P31: turning a P27 CONFIRMED entry into a real Recommendation (pure) -
app/stock_radar/recommendation.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models.domain import AssetType, Candle
from app.stock_radar.entry_confirmation import EntryConfirmation, EntryVerdict
from app.stock_radar.recommendation import build_stock_recommendation
from app.stock_radar.scoring import PreBreakoutScore, ScoreFactor

pytestmark = pytest.mark.P31


def _candle(close: float, day: int) -> Candle:
    start = datetime(2026, 1, 5, tzinfo=UTC) + timedelta(days=day)
    return Candle(
        symbol="005930",
        interval="1d",
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000,
        open_time=start,
        close_time=start + timedelta(days=1),
    )


def _candles(count: int, base: float = 100.0) -> list[Candle]:
    return [_candle(base + i * 0.1, day=i) for i in range(count)]


def _score(**overrides: object) -> PreBreakoutScore:
    defaults: dict[str, object] = {
        "symbol": "005930",
        "total_score": 52.0,
        "max_available": 65.0,
        "reference_close": 100.0,
        "positive": [ScoreFactor("box_compression", 10.0, "변동폭이 최근 구간 중 상위 80%로 압축")],
        "negative": [ScoreFactor("distance_to_high", -2.0, "20일 고점까지 3.0% 남음")],
    }
    defaults.update(overrides)
    return PreBreakoutScore(**defaults)  # type: ignore[arg-type]


def _confirmation(**overrides: object) -> EntryConfirmation:
    defaults: dict[str, object] = {
        "symbol": "005930",
        "verdict": EntryVerdict.CONFIRMED,
        "gap_pct": 1.0,
        "current_price": 101.0,
    }
    defaults.update(overrides)
    return EntryConfirmation(**defaults)  # type: ignore[arg-type]


def test_returns_none_when_confirmation_is_rejected() -> None:
    result = build_stock_recommendation(
        _score(), _confirmation(verdict=EntryVerdict.REJECTED), _candles(20), account_buying_power=10_000_000.0
    )
    assert result is None


def test_raises_on_symbol_mismatch() -> None:
    with pytest.raises(ValueError, match="mismatch"):
        build_stock_recommendation(
            _score(symbol="005930"),
            _confirmation(symbol="000660"),
            _candles(20),
            account_buying_power=10_000_000.0,
        )


def test_returns_none_with_insufficient_candle_history() -> None:
    result = build_stock_recommendation(
        _score(), _confirmation(), _candles(5), account_buying_power=10_000_000.0
    )
    assert result is None


def test_builds_recommendation_with_atr_based_stop_and_real_reasons() -> None:
    candles = _candles(20)
    confirmation = _confirmation(current_price=101.0)

    result = build_stock_recommendation(_score(), confirmation, candles, account_buying_power=10_000_000.0)

    assert result is not None
    assert result.symbol == "005930"
    assert result.asset_type == AssetType.STOCK
    assert result.state == "CONFIRMED_BREAKOUT"
    assert result.entry_low == pytest.approx(101.0)
    assert result.entry_high == pytest.approx(101.0 * 1.005)
    assert result.stop_price < result.entry_low
    assert result.t1_price > result.entry_low
    assert result.t2_price > result.t1_price
    assert result.risk_reward > 0
    assert result.reasons == ["변동폭이 최근 구간 중 상위 80%로 압축"]
    assert result.risks == ["20일 고점까지 3.0% 남음"]
    # 52/65 * 100 = 80.0
    assert result.score == pytest.approx(80.0)
    assert result.id == "stock-radar-005930"
    assert result.expires_at > result.created_at


@pytest.mark.P33
def test_carries_display_name_when_given() -> None:
    result = build_stock_recommendation(
        _score(), _confirmation(), _candles(20), account_buying_power=10_000_000.0, name="삼성전자"
    )
    assert result is not None
    assert result.name == "삼성전자"


@pytest.mark.P33
def test_name_defaults_to_none_not_fabricated() -> None:
    result = build_stock_recommendation(_score(), _confirmation(), _candles(20), account_buying_power=10_000_000.0)
    assert result is not None
    assert result.name is None


def test_uses_fallback_reason_and_risk_when_score_has_no_factors() -> None:
    score = _score(positive=[], negative=[])
    result = build_stock_recommendation(score, _confirmation(), _candles(20), account_buying_power=10_000_000.0)

    assert result is not None
    assert result.reasons == ["가격 압축 및 거래량 신호 기반 돌파 후보"]
    assert result.risks == ["일반적인 돌파 리스크: 돌파 이후 되돌림(실패한 돌파) 가능성"]


def test_returns_none_when_current_price_is_not_positive() -> None:
    result = build_stock_recommendation(
        _score(), _confirmation(current_price=0.0), _candles(20), account_buying_power=10_000_000.0
    )
    assert result is None


def test_returns_none_when_atr_stop_would_be_non_positive() -> None:
    # A tiny current_price with the default 2x ATR stop distance pushes the
    # stop to/through zero - must decline rather than emit a negative stop.
    result = build_stock_recommendation(
        _score(), _confirmation(current_price=0.5), _candles(20), account_buying_power=10_000_000.0
    )
    assert result is None
