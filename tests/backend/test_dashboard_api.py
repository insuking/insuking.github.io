"""P21 acceptance: dashboard.py against the real local Postgres/Redis - the
home screen's summary aggregates real rows (never sample data), the
incidents list surfaces P19 incidents, and performance keeps real and paper
PnL separate.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

import app.api.dashboard as dashboard_api
from app.account.balance import CombinedBalance
from app.account.persistence import persist_balance_snapshot
from app.core.config import get_settings
from app.db.models import (
    AccountBalanceSnapshotRow,
    Approval,
    Candle,
    DailyDecisionRow,
    Fill,
    Incident,
    KakaoAccount,
    MacroSnapshotRow,
    Order,
    OverheatScoreRow,
    PaperAccount,
    PaperFill,
    PaperOrder,
    PaperPosition,
    Position,
    RiskStateRow,
    SystemHealthRow,
)
from app.db.models import Recommendation as RecommendationRow
from app.db.session import session_scope
from app.guardian.health import SERVICE_NAME as GUARDIAN_SERVICE
from app.guardian.health import record_heartbeat
from app.integrations.kis.rest_client import KisRestClient
from app.integrations.upbit.errors import UpbitApiError
from app.integrations.upbit.rest_client import UpbitRestClient
from app.main import app
from app.models.domain import HealthState
from app.radar.macro_persistence import persist_macro_snapshot
from app.radar.macro_regime import MacroReading, MacroRegime
from app.stock_radar.decision import DecisionState, EntryDecision
from app.stock_radar.decision_persistence import persist_daily_decision
from app.stock_radar.overheat import HeatScore, HeatStatus
from app.stock_radar.regime_persistence import upsert_heat_score

pytestmark = [pytest.mark.P21, pytest.mark.asyncio]

_SYMBOL = "DASH-TEST-SYM"
_PAPER_ACCOUNT_ID = "test-dashboard-paper-account"
_EMERGENCY_TEST_USER = "test-dashboard-emergency-user"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(SystemHealthRow).where(SystemHealthRow.service == GUARDIAN_SERVICE))
        await session.execute(delete(RiskStateRow).where(RiskStateRow.daily_loss_limit == 999999.0))
        await session.execute(delete(RiskStateRow).where(RiskStateRow.daily_loss_limit == 888888.0))
        await session.execute(delete(Position).where(Position.symbol == _SYMBOL))
        await session.execute(delete(RecommendationRow).where(RecommendationRow.symbol == _SYMBOL))
        await session.execute(delete(Approval).where(Approval.user_id == "test-dashboard-user"))
        await session.execute(delete(KakaoAccount).where(KakaoAccount.user_id == "test-dashboard-user"))
        await session.execute(delete(Incident).where(Incident.service == "test-dashboard-service"))
        await session.execute(delete(Candle).where(Candle.symbol.in_([_SYMBOL, "KRW-BTC", "0001"])))
        await session.execute(delete(OverheatScoreRow).where(OverheatScoreRow.symbol == _SYMBOL))
        await session.execute(delete(DailyDecisionRow).where(DailyDecisionRow.market_regime == "TEST-DASH-REGIME"))
        await session.execute(delete(MacroSnapshotRow).where(MacroSnapshotRow.headline.like("TEST-DASH-MACRO%")))

        await session.execute(delete(Fill).where(Fill.order_id.like("dash-order-%")))
        await session.execute(delete(Order).where(Order.id.like("dash-order-%")))

        await session.execute(delete(PaperFill).where(PaperFill.order_id.like("dash-paper-order-%")))
        await session.execute(delete(PaperOrder).where(PaperOrder.id.like("dash-paper-order-%")))
        await session.execute(delete(PaperPosition).where(PaperPosition.account_id == _PAPER_ACCOUNT_ID))
        await session.execute(delete(PaperAccount).where(PaperAccount.id == _PAPER_ACCOUNT_ID))
        await session.execute(
            delete(RiskStateRow).where(RiskStateRow.kill_switch_reason.like(f"%{_EMERGENCY_TEST_USER}%"))
        )
        await session.execute(delete(AccountBalanceSnapshotRow).where(AccountBalanceSnapshotRow.total_assets.in_([111.0, 222.0, 333.0])))
        await session.execute(delete(KakaoAccount).where(KakaoAccount.user_id == _EMERGENCY_TEST_USER))
        await session.commit()


async def _seed_valid_kakao_session(user_id: str) -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            KakaoAccount(
                id=f"kakao-{user_id}",
                user_id=user_id,
                kakao_user_id=f"kakao-uid-{user_id}",
                access_token="valid-access-token",
                refresh_token="valid-refresh-token",
                access_expires_at=now + timedelta(hours=6),
                refresh_expires_at=now + timedelta(days=60),
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_summary_reports_offline_guardian_and_empty_lists_on_a_clean_slate() -> None:
    async with await _client() as client:
        response = await client.get("/api/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    guardian = next(sh for sh in body["service_health"] if sh["service"] == GUARDIAN_SERVICE)
    assert guardian["state"] == "OFFLINE"
    assert body["market_regime"] is None  # no KOSPI candles persisted yet on a clean slate
    assert body["macro_regime"] is None  # no macro snapshot persisted yet on a clean slate


async def test_summary_reflects_healthy_guardian_heartbeat() -> None:
    async with session_scope() as session:
        await record_heartbeat(session, state=HealthState.HEALTHY)

    async with await _client() as client:
        response = await client.get("/api/dashboard/summary")
    body = response.json()
    guardian = next(sh for sh in body["service_health"] if sh["service"] == GUARDIAN_SERVICE)
    assert guardian["state"] == "HEALTHY"
    assert body["overall_health"] == "HEALTHY"


async def test_summary_counts_open_incidents() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            Incident(
                id="dash-incident-1",
                service="test-dashboard-service",
                severity="HIGH",
                failure_type="POSITION_MISMATCH",
                detected_at=now,
                human_action_required=True,
            )
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/summary")
    assert response.json()["open_incidents"] >= 1


async def test_summary_includes_open_positions() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            Position(
                id="dash-pos-1",
                symbol=_SYMBOL,
                asset_type="CRYPTO",
                quantity=10.0,
                avg_entry_price=100.0,
                stop_price=90.0,
                state="OPEN",
                guardian_active=True,
                opened_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/summary")
    symbols = [p["symbol"] for p in response.json()["positions"]]
    assert _SYMBOL in symbols


async def test_summary_uses_latest_risk_state() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            RiskStateRow(
                id="dash-risk-1",
                as_of=now,
                daily_loss=1000.0,
                daily_loss_limit=999999.0,
                exposure=5000.0,
                exposure_limit=100000.0,
                open_positions=1,
                max_positions=5,
                consecutive_stops=0,
                kill_switch_active=False,
            )
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/summary")
    risk_used = response.json()["risk_used"]
    assert risk_used is not None
    assert risk_used["daily_loss_limit"] == 999999.0


async def test_summary_top_opportunities_excludes_expired_recommendations() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            RecommendationRow(
                id="dash-rec-expired",
                symbol=_SYMBOL,
                asset_type="CRYPTO",
                score=99.0,
                state="CONFIRMED_BREAKOUT",
                entry_low=100.0,
                entry_high=101.0,
                stop_price=95.0,
                t1_price=105.0,
                t1_percent=30.0,
                t2_price=110.0,
                t2_percent=30.0,
                runner_percent=40.0,
                expected_max_loss=50.0,
                risk_reward=2.0,
                reasons="[]",
                risks="[]",
                created_at=now - timedelta(minutes=10),
                expires_at=now - timedelta(minutes=1),
            )
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/summary")
    ids = [r["id"] for r in response.json()["top_opportunities"]]
    assert "dash-rec-expired" not in ids


@pytest.mark.P33
async def test_summary_top_opportunities_carries_the_recommendation_name() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            RecommendationRow(
                id="dash-rec-named",
                symbol=_SYMBOL,
                name="테스트코인",
                asset_type="CRYPTO",
                score=99.0,
                state="CONFIRMED_BREAKOUT",
                entry_low=100.0,
                entry_high=101.0,
                stop_price=95.0,
                t1_price=105.0,
                t1_percent=30.0,
                t2_price=110.0,
                t2_percent=30.0,
                runner_percent=40.0,
                expected_max_loss=50.0,
                risk_reward=2.0,
                reasons="[]",
                risks="[]",
                created_at=now,
                expires_at=now + timedelta(minutes=10),
            )
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/summary")
    by_id = {r["id"]: r for r in response.json()["top_opportunities"]}
    assert by_id["dash-rec-named"]["name"] == "테스트코인"


async def test_summary_btc_regime_computed_from_real_candles() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        for i in range(21):
            session.add(
                Candle(
                    id=f"dash-btc-candle-{i}",
                    symbol="KRW-BTC",
                    interval="1m",
                    open=100.0 + i,
                    high=101.0 + i,
                    low=99.0 + i,
                    close=100.5 + i,
                    volume=10.0,
                    open_time=now - timedelta(minutes=21 - i),
                    close_time=now - timedelta(minutes=20 - i),
                )
            )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/summary")
    # A steadily rising close series above its own moving average -> RISK_ON.
    assert response.json()["btc_regime"] == "RISK_ON"


@pytest.mark.P37
async def test_summary_market_regime_computed_from_real_kospi_candles() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        for i in range(21):
            session.add(
                Candle(
                    id=f"dash-kospi-candle-{i}",
                    symbol="0001",
                    interval="1d",
                    open=2500.0 + i,
                    high=2510.0 + i,
                    low=2490.0 + i,
                    close=2505.0 + i,
                    volume=1000.0,
                    open_time=now - timedelta(days=21 - i),
                    close_time=now - timedelta(days=20 - i),
                )
            )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/summary")
    body = response.json()
    # A steadily rising close series above its own moving average -> RISK_ON.
    assert body["market_regime"] == "RISK_ON"
    # P37: the reading is timestamped from the newest candle, not just labeled.
    assert body["market_regime_updated_at"] is not None


@pytest.mark.P36
async def test_summary_carries_the_latest_daily_stock_decision() -> None:
    observed_at = datetime.now(UTC)
    async with session_scope() as session:
        await persist_daily_decision(
            session,
            market_regime="TEST-DASH-REGIME",
            daily_state=DecisionState.STRONG_BUY,
            top_symbol="005930",
            top_symbol_name="삼성전자",
            top_decision=EntryDecision(DecisionState.STRONG_BUY, 80.0, 89.0, "5/5 filters"),
            observed_at=observed_at,
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/summary")
    body = response.json()
    assert body["stock_decision_state"] == "STRONG_BUY"
    assert body["stock_decision_top_symbol"] == "005930"
    assert body["stock_decision_top_symbol_name"] == "삼성전자"


@pytest.mark.P38
async def test_summary_carries_the_latest_macro_snapshot() -> None:
    observed_at = datetime.now(UTC)
    reading = MacroReading(
        sp500_change_pct=-2.0, sox_change_pct=-3.0, vix_level=28.0,
        oil_change_pct=1.0, usdkrw_change_pct=0.5,
    )
    async with session_scope() as session:
        await persist_macro_snapshot(
            session, reading, regime=MacroRegime.RISK_OFF,
            headline="TEST-DASH-MACRO VIX 28.0 (공포 구간)", observed_at=observed_at,
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/summary")
    body = response.json()
    assert body["macro_regime"] == "RISK_OFF"
    assert body["macro_headline"] == "TEST-DASH-MACRO VIX 28.0 (공포 구간)"
    assert body["macro_observed_at"] is not None


async def test_incidents_endpoint_returns_seeded_incident() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            Incident(
                id="dash-incident-list-1",
                service="test-dashboard-service",
                severity="LOW",
                failure_type="API_TIMEOUT",
                detected_at=now,
                human_action_required=False,
            )
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/incidents")
    ids = [i["id"] for i in response.json()]
    assert "dash-incident-list-1" in ids


async def test_performance_keeps_real_and_paper_pnl_separate() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        order = Order(
            id="dash-order-1",
            trade_plan_id=None,
            symbol=_SYMBOL,
            side="BUY",
            order_type="MARKET",
            quantity=10.0,
            price=100.0,
            status="FILLED",
            broker="TOSS",
            created_at=now,
            updated_at=now,
        )
        session.add(order)

        sell_order = Order(
            id="dash-order-2",
            trade_plan_id=None,
            symbol=_SYMBOL,
            side="SELL",
            order_type="MARKET",
            quantity=10.0,
            price=120.0,
            status="FILLED",
            broker="TOSS",
            created_at=now,
            updated_at=now,
        )
        session.add(sell_order)

        session.add(
            PaperAccount(
                id=_PAPER_ACCOUNT_ID,
                asset_type="STOCK",
                cash_balance=1_000_000.0,
                created_at=now,
                updated_at=now,
            )
        )
        paper_buy = PaperOrder(
            id="dash-paper-order-1",
            account_id=_PAPER_ACCOUNT_ID,
            symbol=_SYMBOL,
            side="BUY",
            order_type="MARKET",
            quantity=5.0,
            limit_price=None,
            status="FILLED",
            created_at=now,
            updated_at=now,
        )
        session.add(paper_buy)
        paper_sell = PaperOrder(
            id="dash-paper-order-2",
            account_id=_PAPER_ACCOUNT_ID,
            symbol=_SYMBOL,
            side="SELL",
            order_type="MARKET",
            quantity=5.0,
            limit_price=None,
            status="FILLED",
            created_at=now,
            updated_at=now,
        )
        session.add(paper_sell)

        # Flushed before any Fill/PaperFill rows are added: Fill/PaperFill
        # have no ORM `relationship()` back to Order/PaperOrder (plain FK
        # columns only, see app/db/models.py), so nothing here guarantees
        # insert ordering across the two tables within one flush - an
        # explicit flush point avoids relying on that.
        await session.flush()

        session.add(Fill(id="dash-fill-1", order_id=order.id, quantity=10.0, price=100.0, filled_at=now))
        session.add(
            Fill(id="dash-fill-2", order_id=sell_order.id, quantity=10.0, price=120.0, filled_at=now)
        )
        session.add(
            PaperFill(
                id="dash-paper-fill-1",
                order_id=paper_buy.id,
                quantity=5.0,
                price=50.0,
                slippage_amount=0.0,
                commission=0.0,
                tax=0.0,
                latency_ms=0,
                filled_at=now,
            )
        )
        session.add(
            PaperFill(
                id="dash-paper-fill-2",
                order_id=paper_sell.id,
                quantity=5.0,
                price=40.0,  # a loss, unlike the real trade's gain above
                slippage_amount=0.0,
                commission=0.0,
                tax=0.0,
                latency_ms=0,
                filled_at=now,
            )
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/performance")
    body = response.json()
    assert body["real"]["realized_pnl"] >= 200.0  # (120-100)*10, plus whatever pre-existed
    assert body["real"]["win_count"] >= 1
    assert body["paper"]["realized_pnl"] <= -50.0  # (40-50)*5, plus whatever pre-existed
    assert body["paper"]["loss_count"] >= 1


@pytest.mark.P36
@pytest.mark.P35
async def test_performance_reports_risk_avoidance_counts_from_the_last_7_days() -> None:
    now = datetime.now(UTC)
    too_late_heat = HeatScore(9.0, 9.0, 9.0, None, None, 1.0, None, 112.5, HeatStatus.TOO_LATE)

    async with session_scope() as session:
        await upsert_heat_score(session, symbol=_SYMBOL, score=too_late_heat, observed_at=now)
        await persist_daily_decision(
            session, market_regime="TEST-DASH-REGIME", daily_state=DecisionState.NO_TRADE_DAY,
            top_symbol=None, top_symbol_name=None, top_decision=None, observed_at=now,
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/performance")
    avoidance = response.json()["risk_avoidance"]
    assert avoidance["too_late_excluded_count"] >= 1
    assert avoidance["no_trade_day_count"] >= 1
    assert avoidance["window_days"] == 7


@pytest.mark.P42
async def test_positions_live_prices_computes_unrealized_pnl_for_a_crypto_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_get_ticker_price(self: UpbitRestClient, market: str) -> float:
        return 90.0

    monkeypatch.setattr(UpbitRestClient, "get_ticker_price", _fake_get_ticker_price)

    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            Position(
                id="dash-pos-live-crypto", symbol=_SYMBOL, asset_type="CRYPTO", quantity=2.0,
                avg_entry_price=80.0, stop_price=70.0, state="OPEN", guardian_active=True,
                opened_at=now, updated_at=now,
            )
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/positions/live-prices")

    assert response.status_code == 200
    entry = next(p for p in response.json()["prices"] if p["symbol"] == _SYMBOL)
    assert entry["current_price"] == pytest.approx(90.0)
    assert entry["unrealized_pnl"] == pytest.approx((90.0 - 80.0) * 2.0)
    assert entry["unrealized_pnl_pct"] == pytest.approx(12.5)


@pytest.mark.P42
async def test_positions_live_prices_degrades_to_none_when_the_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(self: UpbitRestClient, market: str) -> float:
        raise UpbitApiError(500, "internal_server_error", "temporary")

    monkeypatch.setattr(UpbitRestClient, "get_ticker_price", _boom)

    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            Position(
                id="dash-pos-live-crypto-fail", symbol=_SYMBOL, asset_type="CRYPTO", quantity=1.0,
                avg_entry_price=50.0, stop_price=45.0, state="OPEN", guardian_active=True,
                opened_at=now, updated_at=now,
            )
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/positions/live-prices")

    entry = next(p for p in response.json()["prices"] if p["symbol"] == _SYMBOL)
    assert entry["current_price"] is None
    assert entry["unrealized_pnl"] is None
    assert entry["unrealized_pnl_pct"] is None


@pytest.mark.P42
async def test_positions_live_prices_returns_none_for_a_stock_position_when_kis_is_not_configured() -> None:
    settings = get_settings()
    original_key, original_secret = settings.kis_app_key, settings.kis_app_secret
    settings.kis_app_key = ""
    settings.kis_app_secret = ""
    try:
        now = datetime.now(UTC)
        async with session_scope() as session:
            session.add(
                Position(
                    id="dash-pos-live-stock", symbol=_SYMBOL, asset_type="STOCK", quantity=10.0,
                    avg_entry_price=70000.0, stop_price=68000.0, state="OPEN", guardian_active=True,
                    opened_at=now, updated_at=now,
                )
            )
            await session.commit()

        async with await _client() as client:
            response = await client.get("/api/dashboard/positions/live-prices")
    finally:
        settings.kis_app_key = original_key
        settings.kis_app_secret = original_secret

    entry = next(p for p in response.json()["prices"] if p["symbol"] == _SYMBOL)
    assert entry["current_price"] is None


@pytest.mark.P45
async def test_balance_returns_the_real_combined_total(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_fetch_combined_balance(settings: object) -> CombinedBalance:
        return CombinedBalance(kis_total_value=1_000_000.0, upbit_total_value=500_000.0)

    monkeypatch.setattr(dashboard_api, "fetch_combined_balance", _fake_fetch_combined_balance)

    async with await _client() as client:
        response = await client.get("/api/dashboard/balance")

    assert response.status_code == 200
    body = response.json()
    assert body["kis_total_value"] == 1_000_000.0
    assert body["upbit_total_value"] == 500_000.0
    assert body["total_assets"] == 1_500_000.0


@pytest.mark.P45
async def test_balance_history_returns_real_snapshots_within_the_requested_window() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        await persist_balance_snapshot(session, CombinedBalance(50.0, 61.0), now - timedelta(days=10))  # 111.0
        await persist_balance_snapshot(session, CombinedBalance(100.0, 122.0), now - timedelta(hours=12))  # 222.0
        await persist_balance_snapshot(session, CombinedBalance(150.0, 183.0), now - timedelta(minutes=5))  # 333.0
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/balance/history", params={"window": "1d"})

    assert response.status_code == 200
    body = response.json()
    assert body["window"] == "1d"
    totals = [s["total_assets"] for s in body["snapshots"]]
    assert 111.0 not in totals  # 10 days ago - outside the 1d window
    assert totals == [222.0, 333.0]  # chronological (oldest first), 10-day-old snapshot excluded


@pytest.mark.P45
async def test_balance_history_all_window_includes_everything() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        await persist_balance_snapshot(session, CombinedBalance(50.0, 61.0), now - timedelta(days=10))
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/balance/history", params={"window": "all"})

    totals = [s["total_assets"] for s in response.json()["snapshots"]]
    assert 111.0 in totals


@pytest.mark.P45
async def test_emergency_stop_requires_authentication() -> None:
    async with await _client() as client:
        response = await client.post(
            "/api/dashboard/emergency-stop", headers={"X-User-Id": _EMERGENCY_TEST_USER}
        )

    assert response.status_code == 401


@pytest.mark.P45
async def test_emergency_stop_activates_the_kill_switch_immediately() -> None:
    await _seed_valid_kakao_session(_EMERGENCY_TEST_USER)

    async with await _client() as client:
        response = await client.post(
            "/api/dashboard/emergency-stop", headers={"X-User-Id": _EMERGENCY_TEST_USER}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["kill_switch_active"] is True
    assert _EMERGENCY_TEST_USER in body["kill_switch_reason"]

    async with session_scope() as session:
        result = await session.execute(select(RiskStateRow).order_by(RiskStateRow.as_of.desc()).limit(1))
        latest = result.scalar_one()
    assert latest.kill_switch_active is True


@pytest.mark.P45
async def test_emergency_stop_clear_deactivates_the_kill_switch() -> None:
    await _seed_valid_kakao_session(_EMERGENCY_TEST_USER)

    async with await _client() as client:
        await client.post("/api/dashboard/emergency-stop", headers={"X-User-Id": _EMERGENCY_TEST_USER})
        response = await client.post(
            "/api/dashboard/emergency-stop/clear", headers={"X-User-Id": _EMERGENCY_TEST_USER}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["kill_switch_active"] is False
    assert _EMERGENCY_TEST_USER in body["kill_switch_reason"]


@pytest.mark.P45
async def test_emergency_stop_preserves_real_risk_numbers_from_the_previous_state() -> None:
    await _seed_valid_kakao_session(_EMERGENCY_TEST_USER)
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            RiskStateRow(
                as_of=now,
                daily_loss=12_345.0,
                daily_loss_limit=100_000.0,
                exposure=50_000.0,
                exposure_limit=200_000.0,
                open_positions=2,
                max_positions=5,
                consecutive_stops=1,
                kill_switch_active=False,
                kill_switch_reason=None,
            )
        )
        await session.commit()

    async with await _client() as client:
        await client.post("/api/dashboard/emergency-stop", headers={"X-User-Id": _EMERGENCY_TEST_USER})

    async with session_scope() as session:
        result = await session.execute(select(RiskStateRow).order_by(RiskStateRow.as_of.desc()).limit(1))
        latest = result.scalar_one()
    assert latest.daily_loss == 12_345.0
    assert latest.exposure == 50_000.0
    assert latest.kill_switch_active is True


@pytest.mark.P45
async def test_safety_check_reports_demo_mode_when_live_trading_is_off() -> None:
    settings = get_settings()
    assert settings.live_trading is False  # the project's safe default

    async with await _client() as client:
        response = await client.get("/api/dashboard/safety-check")

    body = response.json()
    demo_item = next(item for item in body["items"] if item["key"] == "demo_mode")
    assert demo_item["status"] == "ok"
    assert demo_item["label"] == "Demo 모드"


@pytest.mark.P45
async def test_safety_check_withdrawal_item_is_always_ok() -> None:
    async with await _client() as client:
        response = await client.get("/api/dashboard/safety-check")

    withdrawal_item = next(item for item in response.json()["items"] if item["key"] == "withdrawal_disabled")
    assert withdrawal_item["status"] == "ok"


@pytest.mark.P45
async def test_safety_check_exchange_connection_ok_when_upbit_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_ticker_price(self: UpbitRestClient, market: str) -> float:
        return 90_000_000.0

    monkeypatch.setattr(UpbitRestClient, "get_ticker_price", _fake_get_ticker_price)

    async with await _client() as client:
        response = await client.get("/api/dashboard/safety-check")

    connection_item = next(item for item in response.json()["items"] if item["key"] == "exchange_connection")
    assert connection_item["status"] == "ok"
    assert "Upbit 정상" in connection_item["detail"]


@pytest.mark.P45
async def test_safety_check_exchange_connection_warns_when_upbit_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(self: UpbitRestClient, market: str) -> float:
        raise UpbitApiError(500, "internal_server_error", "down")

    monkeypatch.setattr(UpbitRestClient, "get_ticker_price", _boom)

    async with await _client() as client:
        response = await client.get("/api/dashboard/safety-check")

    connection_item = next(item for item in response.json()["items"] if item["key"] == "exchange_connection")
    assert connection_item["status"] == "warning"
    assert "연결 실패" in connection_item["detail"]


@pytest.mark.P45
async def test_safety_check_reports_kis_not_configured_without_calling_kis(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_ticker_price(self: UpbitRestClient, market: str) -> float:
        return 90_000_000.0

    async def _fail_if_called(self: KisRestClient, symbol: str, market: object = None) -> object:
        raise AssertionError("KIS should not be called when not configured")

    monkeypatch.setattr(UpbitRestClient, "get_ticker_price", _fake_get_ticker_price)
    monkeypatch.setattr(KisRestClient, "get_quote", _fail_if_called)

    settings = get_settings()
    assert settings.kis_configured is False  # no KIS credentials in this test environment

    async with await _client() as client:
        response = await client.get("/api/dashboard/safety-check")

    connection_item = next(item for item in response.json()["items"] if item["key"] == "exchange_connection")
    assert "KIS 미설정" in connection_item["detail"]


@pytest.mark.P45
async def test_safety_check_daily_loss_limit_ok_when_a_recent_risk_state_has_a_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_get_ticker_price(self: UpbitRestClient, market: str) -> float:
        return 90_000_000.0

    monkeypatch.setattr(UpbitRestClient, "get_ticker_price", _fake_get_ticker_price)

    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            RiskStateRow(
                as_of=now,
                daily_loss=0.0,
                daily_loss_limit=999999.0,  # this file's own cleanup sentinel for RiskStateRow test rows
                exposure=0.0,
                exposure_limit=1_000_000.0,
                open_positions=0,
                max_positions=5,
                consecutive_stops=0,
                kill_switch_active=False,
                kill_switch_reason=None,
            )
        )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/safety-check")

    loss_item = next(item for item in response.json()["items"] if item["key"] == "daily_loss_limit")
    assert loss_item["status"] == "ok"
    assert "999,999" in loss_item["detail"]


@pytest.mark.P46
async def test_risk_state_history_returns_real_rows_newest_first() -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        for offset_minutes, active in ((10, False), (5, True), (0, False)):
            session.add(
                RiskStateRow(
                    as_of=now - timedelta(minutes=offset_minutes),
                    daily_loss=0.0,
                    daily_loss_limit=888888.0,  # this test's own cleanup sentinel
                    exposure=0.0,
                    exposure_limit=1_000_000.0,
                    open_positions=0,
                    max_positions=5,
                    consecutive_stops=0,
                    kill_switch_active=active,
                    kill_switch_reason="사용자 수동 긴급정지" if active else None,
                )
            )
        await session.commit()

    async with await _client() as client:
        response = await client.get("/api/dashboard/risk-states/history")

    assert response.status_code == 200
    sentinel_rows = [s for s in response.json()["snapshots"] if s["daily_loss_limit"] == 888888.0]
    assert len(sentinel_rows) == 3
    # newest first
    timestamps = [s["as_of"] for s in sentinel_rows]
    assert timestamps == sorted(timestamps, reverse=True)
    assert sentinel_rows[1]["kill_switch_active"] is True


@pytest.mark.P46
async def test_risk_state_history_returns_the_real_shape_never_fabricated_fields() -> None:
    """Doesn't force an empty table (this DB is shared across this whole
    test file, and other tests' rows legitimately persist) - just proves
    every field on a real row round-trips honestly, whatever rows exist."""
    async with await _client() as client:
        response = await client.get("/api/dashboard/risk-states/history")

    assert response.status_code == 200
    snapshots = response.json()["snapshots"]
    assert isinstance(snapshots, list)
    for snapshot in snapshots:
        assert set(snapshot.keys()) == {
            "as_of",
            "kill_switch_active",
            "kill_switch_reason",
            "daily_loss",
            "daily_loss_limit",
            "exposure",
            "exposure_limit",
        }
