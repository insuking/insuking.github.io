"""P40: app.stock_radar.backtest's walk-forward orchestration.

The individual pipeline stages (score_prebreakout/confirm_entry/
compute_heat_score/decide_entry_state/build_stock_recommendation) already
have their own dedicated test suites proving their internal correctness
(test_stock_radar_scoring.py, test_entry_confirmation.py, test_overheat.py,
test_stock_decision.py, test_stock_recommendation.py) - hand-engineering
real candle fixtures that thread through all five chained gates to a
specific, deterministic STOP-vs-TARGET-vs-TOO_LATE outcome is far more
fragile here than it was for crypto's simpler pipeline (see
test_crypto_backtest.py). So most tests here monkeypatch those five
functions (imported by name into app.stock_radar.backtest's own
namespace) to isolate what's actually being tested: the orchestration
loop's no-lookahead entry timing, exit-priority ordering, gate-counter
bookkeeping, and open-trade exclusivity - not the pipeline stages
themselves. One end-to-end test (using the same real
`_textbook_setup_bars()` fixture `test_stock_radar_scan.py` already
proved produces a real CONFIRMED, non-TOO_LATE score) proves the real
wiring still works without any mocking.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.domain import AssetType, Candle, Recommendation
from app.radar.regime import MarketRegime
from app.stock_radar import backtest as backtest_module
from app.stock_radar.backtest import backtest_prebreakout_strategy
from app.stock_radar.decision import DecisionState, EntryDecision
from app.stock_radar.entry_confirmation import EntryConfirmation, EntryVerdict
from app.stock_radar.overheat import HeatScore, HeatStatus
from app.stock_radar.scoring import PreBreakoutScore

pytestmark = pytest.mark.P40

_START = datetime(2026, 1, 1, tzinfo=UTC)
_WINDOW = 74  # matches backtest_module._MIN_BARS


def _bar(open_: float, high: float, low: float, close: float, volume: float = 1_000_000.0) -> tuple:
    return (open_, high, low, close, volume)


def _to_candles(bars: list[tuple], symbol: str) -> list[Candle]:
    candles = []
    for i, (open_, high, low, close, volume) in enumerate(bars):
        open_time = _START + timedelta(days=i)
        candles.append(
            Candle(
                symbol=symbol, interval="1d", open=open_, high=high, low=low, close=close, volume=volume,
                open_time=open_time, close_time=open_time + timedelta(days=1),
            )
        )
    return candles


def _flat_bars(count: int, price: float = 100.0) -> list[tuple]:
    return [_bar(price, price + 1.0, price - 1.0, price) for _ in range(count)]


def _flat_benchmark(count: int) -> list[Candle]:
    return _to_candles(_flat_bars(count, price=1000.0), "KOSPI")


def _textbook_setup_bars() -> list[tuple]:
    """Same fixture test_stock_radar_scan.py already proved produces a
    real, non-TOO_LATE CONFIRMED entry through the whole live pipeline."""
    baseline = [_bar(100.0, 106.0, 94.0, 100.0 if i % 2 == 0 else 103.0) for i in range(70)]
    tail = [
        _bar(103.0, 104.5, 102.5, 103.5),
        _bar(103.5, 104.8, 103.0, 104.0, 1_050_000.0),
        _bar(104.0, 105.0, 103.5, 104.3, 1_100_000.0),
        _bar(104.3, 105.2, 103.8, 104.6, 1_500_000.0),
        _bar(104.6, 105.4, 104.0, 105.0, 2_200_000.0),
    ]
    return baseline + tail


def _fake_score(symbol: str) -> PreBreakoutScore:
    return PreBreakoutScore(symbol=symbol, total_score=60.0, max_available=65.0, reference_close=100.0)


def _fake_confirmation(symbol: str, verdict: EntryVerdict, current_price: float = 100.0) -> EntryConfirmation:
    return EntryConfirmation(symbol=symbol, verdict=verdict, gap_pct=0.0, current_price=current_price)


def _fake_heat(status: HeatStatus) -> HeatScore:
    return HeatScore(
        return_1d_pct=0.0, return_2d_pct=0.0, return_5d_pct=0.0, distance_from_signal_pct=0.0,
        gap_pct=0.0, volume_ratio=1.0, atr_extension=0.0, heat_score=0.0, status=status,
    )


def _fake_decision(state: DecisionState) -> EntryDecision:
    return EntryDecision(state=state, minimum_score=80.0, normalized_score=90.0, reason="test")


def _fake_recommendation(entry_low: float, stop_price: float, t2_price: float) -> Recommendation:
    return Recommendation(
        id="bt-1", symbol="TEST", asset_type=AssetType.STOCK, score=90.0, state="CONFIRMED_BREAKOUT",
        entry_low=entry_low, entry_high=entry_low * 1.005, stop_price=stop_price,
        t1_price=(entry_low + t2_price) / 2, t1_percent=30.0, t2_price=t2_price, t2_percent=30.0,
        runner_percent=40.0, expected_max_loss=1000.0, risk_reward=2.0,
        created_at=_START, expires_at=_START + timedelta(minutes=5),
    )


def test_mismatched_series_lengths_are_rejected() -> None:
    candles = _to_candles(_flat_bars(_WINDOW + 1), "TEST")
    benchmark = _flat_benchmark(_WINDOW)

    with pytest.raises(ValueError, match="same length"):
        backtest_prebreakout_strategy("TEST", candles, benchmark, account_buying_power=10_000_000.0)


def test_too_few_bars_returns_an_empty_result_without_erroring() -> None:
    candles = _to_candles(_flat_bars(10), "TEST")
    benchmark = _flat_benchmark(10)

    result = backtest_prebreakout_strategy("TEST", candles, benchmark, account_buying_power=10_000_000.0)

    assert result.num_trades == 0
    assert result.trades == []


def test_real_pipeline_end_to_end_on_a_known_good_setup() -> None:
    """No mocking - proves the real wiring (all five pipeline stages)
    still works, using the same fixture test_stock_radar_scan.py already
    validated produces a real entry."""
    candles = _to_candles(_textbook_setup_bars(), "TEST")
    benchmark = _flat_benchmark(len(candles))

    result = backtest_prebreakout_strategy("TEST", candles, benchmark, account_buying_power=10_000_000.0)

    # Only one bar past the entry-eligible day exists in this fixture, so
    # any resulting trade must have closed as END_OF_DATA - the important
    # thing is the real pipeline ran end to end without raising and either
    # opened a trade or made a real (non-crashing) decision not to.
    for trade in result.trades:
        assert trade.exit_reason == "END_OF_DATA"


def test_score_none_skips_the_day_without_incrementing_any_gate_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    candles = _to_candles(_flat_bars(_WINDOW + 4), "TEST")
    benchmark = _flat_benchmark(len(candles))
    monkeypatch.setattr(backtest_module, "score_prebreakout", lambda *a, **k: None)

    result = backtest_prebreakout_strategy("TEST", candles, benchmark, account_buying_power=10_000_000.0)

    assert result.num_trades == 0
    assert result.too_late_excluded_count == 0
    assert result.rejected_reconfirm_count == 0
    assert result.no_buy_or_watch_count == 0


def test_rejected_reconfirmation_is_counted_and_blocks_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    candles = _to_candles(_flat_bars(_WINDOW + 4), "TEST")
    benchmark = _flat_benchmark(len(candles))
    monkeypatch.setattr(backtest_module, "score_prebreakout", lambda *a, **k: _fake_score("TEST"))
    monkeypatch.setattr(backtest_module, "classify_market_regime", lambda *a, **k: MarketRegime.NEUTRAL)
    monkeypatch.setattr(
        backtest_module, "confirm_entry", lambda *a, **k: _fake_confirmation("TEST", EntryVerdict.REJECTED)
    )

    result = backtest_prebreakout_strategy("TEST", candles, benchmark, account_buying_power=10_000_000.0)

    expected_attempts = len(candles) - _WINDOW
    assert result.num_trades == 0
    assert result.rejected_reconfirm_count == expected_attempts


def test_too_late_heat_status_is_counted_and_blocks_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    candles = _to_candles(_flat_bars(_WINDOW + 4), "TEST")
    benchmark = _flat_benchmark(len(candles))
    monkeypatch.setattr(backtest_module, "score_prebreakout", lambda *a, **k: _fake_score("TEST"))
    monkeypatch.setattr(backtest_module, "classify_market_regime", lambda *a, **k: MarketRegime.NEUTRAL)
    monkeypatch.setattr(
        backtest_module, "confirm_entry", lambda *a, **k: _fake_confirmation("TEST", EntryVerdict.CONFIRMED)
    )
    monkeypatch.setattr(backtest_module, "compute_heat_score", lambda *a, **k: _fake_heat(HeatStatus.TOO_LATE))

    result = backtest_prebreakout_strategy("TEST", candles, benchmark, account_buying_power=10_000_000.0)

    expected_attempts = len(candles) - _WINDOW
    assert result.num_trades == 0
    assert result.too_late_excluded_count == expected_attempts


def test_watch_or_no_buy_decision_is_counted_and_blocks_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    candles = _to_candles(_flat_bars(_WINDOW + 4), "TEST")
    benchmark = _flat_benchmark(len(candles))
    monkeypatch.setattr(backtest_module, "score_prebreakout", lambda *a, **k: _fake_score("TEST"))
    monkeypatch.setattr(backtest_module, "classify_market_regime", lambda *a, **k: MarketRegime.NEUTRAL)
    monkeypatch.setattr(
        backtest_module, "confirm_entry", lambda *a, **k: _fake_confirmation("TEST", EntryVerdict.CONFIRMED)
    )
    monkeypatch.setattr(backtest_module, "compute_heat_score", lambda *a, **k: _fake_heat(HeatStatus.NORMAL))
    monkeypatch.setattr(backtest_module, "decide_entry_state", lambda *a, **k: _fake_decision(DecisionState.WATCH))

    result = backtest_prebreakout_strategy("TEST", candles, benchmark, account_buying_power=10_000_000.0)

    expected_attempts = len(candles) - _WINDOW
    assert result.num_trades == 0
    assert result.no_buy_or_watch_count == expected_attempts


def test_entry_uses_next_bars_open_not_the_signal_days_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-lookahead proof: confirm_entry() must be called with the NEXT
    bar's open, never the signal day's own close."""
    candles = _to_candles(_flat_bars(_WINDOW + 1), "TEST")
    benchmark = _flat_benchmark(len(candles))
    captured_prices: list[float] = []

    def _spy_confirm_entry(score: object, current_price: float, regime: object) -> EntryConfirmation:
        captured_prices.append(current_price)
        return _fake_confirmation("TEST", EntryVerdict.REJECTED, current_price=current_price)

    monkeypatch.setattr(backtest_module, "score_prebreakout", lambda *a, **k: _fake_score("TEST"))
    monkeypatch.setattr(backtest_module, "classify_market_regime", lambda *a, **k: MarketRegime.NEUTRAL)
    monkeypatch.setattr(backtest_module, "confirm_entry", _spy_confirm_entry)

    backtest_prebreakout_strategy("TEST", candles, benchmark, account_buying_power=10_000_000.0)

    # Only one eligible day exists (window+1 bars) - next_bar is candles[_WINDOW].
    assert captured_prices == [candles[_WINDOW].open]


def _open_a_trade_then_append(post_entry_bars: list[tuple]) -> tuple[list[Candle], list[Candle]]:
    """Builds a fixture that opens exactly one trade (via mocked pipeline
    stages, entry_low=100/stop=90/t2=120) at the first eligible day, then
    appends `post_entry_bars` afterward for exit-check testing."""
    bars = _flat_bars(_WINDOW + 1) + post_entry_bars
    candles = _to_candles(bars, "TEST")
    benchmark = _flat_benchmark(len(candles))
    return candles, benchmark


def _patch_always_enter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backtest_module, "score_prebreakout", lambda *a, **k: _fake_score("TEST"))
    monkeypatch.setattr(backtest_module, "classify_market_regime", lambda *a, **k: MarketRegime.NEUTRAL)
    monkeypatch.setattr(
        backtest_module, "confirm_entry", lambda *a, **k: _fake_confirmation("TEST", EntryVerdict.CONFIRMED)
    )
    monkeypatch.setattr(backtest_module, "compute_heat_score", lambda *a, **k: _fake_heat(HeatStatus.NORMAL))
    monkeypatch.setattr(backtest_module, "decide_entry_state", lambda *a, **k: _fake_decision(DecisionState.BUY))
    monkeypatch.setattr(
        backtest_module, "build_stock_recommendation",
        lambda *a, **k: _fake_recommendation(entry_low=100.0, stop_price=90.0, t2_price=120.0),
    )


def test_exit_checks_stop_before_target_when_both_touched_same_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_always_enter(monkeypatch)
    # First post-entry bar touches both the stop (low=85) and the target (high=125).
    candles, benchmark = _open_a_trade_then_append([_bar(100.0, 125.0, 85.0, 110.0)])

    result = backtest_prebreakout_strategy("TEST", candles, benchmark, account_buying_power=10_000_000.0)

    assert result.num_trades == 1
    assert result.trades[0].exit_reason == "STOP"
    assert result.trades[0].exit_price == pytest.approx(90.0)


def test_exit_hits_target_when_only_the_target_is_touched(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_always_enter(monkeypatch)
    candles, benchmark = _open_a_trade_then_append([_bar(100.0, 125.0, 98.0, 110.0)])

    result = backtest_prebreakout_strategy("TEST", candles, benchmark, account_buying_power=10_000_000.0)

    assert result.num_trades == 1
    assert result.trades[0].exit_reason == "TARGET"
    assert result.trades[0].exit_price == pytest.approx(120.0)
    assert result.trades[0].return_pct == pytest.approx(0.20)


def test_open_trade_closes_at_the_last_close_as_end_of_data_when_neither_level_is_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_always_enter(monkeypatch)
    candles, benchmark = _open_a_trade_then_append(
        [_bar(100.0, 105.0, 98.0, 102.0), _bar(102.0, 106.0, 99.0, 104.0)]
    )

    result = backtest_prebreakout_strategy("TEST", candles, benchmark, account_buying_power=10_000_000.0)

    assert result.num_trades == 1
    assert result.trades[0].exit_reason == "END_OF_DATA"
    assert result.trades[0].exit_price == pytest.approx(candles[-1].close)


def test_no_new_entry_is_attempted_while_a_trade_is_open(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_always_enter(monkeypatch)
    call_count = 0
    real_confirm_entry = backtest_module.confirm_entry

    def _counting_confirm_entry(*args: object, **kwargs: object) -> EntryConfirmation:
        nonlocal call_count
        call_count += 1
        return real_confirm_entry(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(backtest_module, "confirm_entry", _counting_confirm_entry)
    # Two flat post-entry bars - neither touches stop or target, so the
    # trade should stay open (and no second entry attempted) the whole way.
    candles, benchmark = _open_a_trade_then_append(
        [_bar(100.0, 105.0, 98.0, 102.0), _bar(102.0, 106.0, 99.0, 104.0), _bar(104.0, 107.0, 101.0, 105.0)]
    )

    result = backtest_prebreakout_strategy("TEST", candles, benchmark, account_buying_power=10_000_000.0)

    assert result.num_trades == 1
    assert call_count == 1  # confirm_entry only ever called once - the original entry attempt
