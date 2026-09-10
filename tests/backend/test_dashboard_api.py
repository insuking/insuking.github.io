"""P21 acceptance: dashboard.py against the real local Postgres/Redis - the
home screen's summary aggregates real rows (never sample data), the
incidents list surfaces P19 incidents, and performance keeps real and paper
PnL separate.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.db.models import (
    Approval,
    Candle,
    DailyDecisionRow,
    Fill,
    Incident,
    KakaoAccount,
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
from app.main import app
from app.models.domain import HealthState
from app.stock_radar.decision import DecisionState, EntryDecision
from app.stock_radar.decision_persistence import persist_daily_decision
from app.stock_radar.overheat import HeatScore, HeatStatus
from app.stock_radar.regime_persistence import upsert_heat_score

pytestmark = [pytest.mark.P21, pytest.mark.asyncio]

_SYMBOL = "DASH-TEST-SYM"
_PAPER_ACCOUNT_ID = "test-dashboard-paper-account"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(SystemHealthRow).where(SystemHealthRow.service == GUARDIAN_SERVICE))
        await session.execute(delete(RiskStateRow).where(RiskStateRow.daily_loss_limit == 999999.0))
        await session.execute(delete(Position).where(Position.symbol == _SYMBOL))
        await session.execute(delete(RecommendationRow).where(RecommendationRow.symbol == _SYMBOL))
        await session.execute(delete(Approval).where(Approval.user_id == "test-dashboard-user"))
        await session.execute(delete(KakaoAccount).where(KakaoAccount.user_id == "test-dashboard-user"))
        await session.execute(delete(Incident).where(Incident.service == "test-dashboard-service"))
        await session.execute(delete(Candle).where(Candle.symbol.in_([_SYMBOL, "KRW-BTC", "0001"])))
        await session.execute(delete(OverheatScoreRow).where(OverheatScoreRow.symbol == _SYMBOL))
        await session.execute(delete(DailyDecisionRow).where(DailyDecisionRow.market_regime == "TEST-DASH-REGIME"))

        await session.execute(delete(Fill).where(Fill.order_id.like("dash-order-%")))
        await session.execute(delete(Order).where(Order.id.like("dash-order-%")))

        await session.execute(delete(PaperFill).where(PaperFill.order_id.like("dash-paper-order-%")))
        await session.execute(delete(PaperOrder).where(PaperOrder.id.like("dash-paper-order-%")))
        await session.execute(delete(PaperPosition).where(PaperPosition.account_id == _PAPER_ACCOUNT_ID))
        await session.execute(delete(PaperAccount).where(PaperAccount.id == _PAPER_ACCOUNT_ID))
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
