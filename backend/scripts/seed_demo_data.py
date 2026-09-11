#!/usr/bin/env python3
"""Seed demo data for local exploration (docker compose / dev DB only).

Inserts a small, clearly-labeled set of rows so the P21 UI has something to
show on first run instead of every screen reading empty: one crypto and one
stock recommendation, one open position, a risk snapshot, a healthy Guardian
heartbeat, a resolved incident, and enough KRW-BTC candles for the market
regime classifier to produce a real (not null) reading.

This is a local-development convenience only - it writes directly into
whatever `DATABASE_URL` this process resolves to (see app/core/config.py),
never touches a real broker/exchange, and every id is prefixed `demo-` so a
second run cleans up and replaces the same rows rather than accumulating
duplicates. Not part of the application; nothing imports this module.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, ".")

from sqlalchemy import delete

from app.db.models import (
    Candle,
    DailyDecisionRow,
    Incident,
    MacroSnapshotRow,
    OverheatScoreRow,
    Position,
    Recommendation,
    RiskStateRow,
)
from app.db.session import session_scope
from app.guardian.health import SERVICE_NAME as GUARDIAN_SERVICE
from app.guardian.health import record_heartbeat
from app.models.domain import HealthState

_DEMO_SYMBOL = "KRW-BTC"
_DEMO_KOSPI_SYMBOL = "0001"


async def _clear_previous() -> None:
    async with session_scope() as session:
        await session.execute(delete(Recommendation).where(Recommendation.id.like("demo-%")))
        await session.execute(delete(Position).where(Position.id.like("demo-%")))
        await session.execute(delete(RiskStateRow).where(RiskStateRow.id.like("demo-%")))
        await session.execute(delete(Incident).where(Incident.id.like("demo-%")))
        await session.execute(delete(Candle).where(Candle.id.like("demo-%")))
        await session.execute(delete(DailyDecisionRow).where(DailyDecisionRow.market_regime == "DEMO"))
        await session.execute(delete(OverheatScoreRow).where(OverheatScoreRow.symbol.like("DEMO-%")))
        await session.execute(delete(MacroSnapshotRow).where(MacroSnapshotRow.headline.like("DEMO-%")))
        await session.commit()


async def seed() -> None:
    await _clear_previous()
    now = datetime.now(UTC)

    async with session_scope() as session:
        session.add(
            Recommendation(
                id="demo-rec-1",
                symbol="KRW-XRP",
                asset_type="CRYPTO",
                score=92.0,
                state="CONFIRMED_BREAKOUT",
                entry_low=4080.0,
                entry_high=4130.0,
                stop_price=3980.0,
                t1_price=4270.0,
                t1_percent=30.0,
                t2_price=4450.0,
                t2_percent=30.0,
                runner_percent=40.0,
                expected_max_loss=9500.0,
                risk_reward=2.1,
                reasons=(
                    '["시가 범위 고점 돌파 확정", '
                    '"평균 거래량 대비 2.4배 (RVOL)", "벤치마크 대비 3.2% 초과 수익"]'
                ),
                risks='["일반적인 돌파 리스크: 돌파 이후 되돌림(실패한 돌파) 가능성"]',
                created_at=now,
                expires_at=now + timedelta(minutes=2, seconds=30),
            )
        )
        session.add(
            Recommendation(
                id="demo-rec-2",
                symbol="005930",
                asset_type="STOCK",
                score=78.0,
                state="PRE_BREAKOUT",
                entry_low=71000.0,
                entry_high=71500.0,
                stop_price=69800.0,
                t1_price=73000.0,
                t1_percent=30.0,
                t2_price=74500.0,
                t2_percent=30.0,
                runner_percent=40.0,
                expected_max_loss=120000.0,
                risk_reward=1.8,
                reasons='["시가 범위 고점 부근에서 좁혀지는 변동폭", "섹터 상대강도 양호"]',
                risks='["시장 국면이 중립(NEUTRAL) - 확신도 낮음"]',
                created_at=now,
                expires_at=now + timedelta(minutes=4),
            )
        )
        session.add(
            Position(
                id="demo-pos-1",
                symbol=_DEMO_SYMBOL,
                asset_type="CRYPTO",
                quantity=0.05,
                avg_entry_price=82_000_000.0,
                stop_price=79_500_000.0,
                state="T1_FILLED",
                guardian_active=True,
                opened_at=now - timedelta(hours=3),
                updated_at=now,
            )
        )
        session.add(
            RiskStateRow(
                id="demo-risk-1",
                as_of=now,
                daily_loss=45_000.0,
                daily_loss_limit=300_000.0,
                exposure=4_100_000.0,
                exposure_limit=10_000_000.0,
                open_positions=1,
                max_positions=5,
                consecutive_stops=0,
                kill_switch_active=False,
            )
        )
        session.add(
            Incident(
                id="demo-incident-1",
                service="upbit-ws",
                severity="LOW",
                failure_type="WEBSOCKET_DISCONNECT",
                detected_at=now - timedelta(minutes=12),
                safe_action="attempting automatic recovery",
                recovery_attempts=1,
                recovered_at=now - timedelta(minutes=11),
                verification_result="VERIFIED",
                human_action_required=False,
            )
        )
        for i in range(21):
            session.add(
                Candle(
                    id=f"demo-btc-candle-{i}",
                    symbol=_DEMO_SYMBOL,
                    interval="1m",
                    open=82_000_000.0 + i * 15_000,
                    high=82_100_000.0 + i * 15_000,
                    low=81_900_000.0 + i * 15_000,
                    close=82_050_000.0 + i * 15_000,
                    volume=3.2,
                    open_time=now - timedelta(minutes=21 - i),
                    close_time=now - timedelta(minutes=20 - i),
                )
            )
        # P37: real daily KOSPI candles so the 시장 tab's domestic-market
        # regime read has something to classify from - a gentle uptrend so
        # the demo shows RISK_ON, not another "데이터 없음".
        for i in range(21):
            close = 2_600.0 + i * 3.5
            session.add(
                Candle(
                    id=f"demo-kospi-candle-{i}",
                    symbol=_DEMO_KOSPI_SYMBOL,
                    interval="1d",
                    open=close - 5.0,
                    high=close + 6.0,
                    low=close - 8.0,
                    close=close,
                    volume=450_000_000.0,
                    open_time=now - timedelta(days=21 - i),
                    close_time=now - timedelta(days=20 - i),
                )
            )
        # P36: today's no-trade decision so the 시장 탭's "오늘의 판정" card
        # and the 성과 탭's risk_avoidance count have something real to show.
        session.add(
            DailyDecisionRow(
                id="demo-decision-1",
                observed_at=now,
                market_regime="DEMO",
                minimum_score=82.0,
                decision_state="BUY",
                top_symbol="005930",
                top_symbol_name="삼성전자",
                top_normalized_score=86.5,
                entry_filters_passed=6,
                entry_filters_total=7,
                reason="PRE-BREAKOUT 86.5점, TOO LATE 아님, 진입필터 6/7 통과",
                created_at=now,
            )
        )
        session.add(
            DailyDecisionRow(
                id="demo-decision-2",
                observed_at=now - timedelta(days=1),
                market_regime="DEMO",
                minimum_score=85.0,
                decision_state="NO_TRADE_DAY",
                top_symbol=None,
                top_symbol_name=None,
                top_normalized_score=None,
                entry_filters_passed=None,
                entry_filters_total=None,
                reason="오늘 재확인된 CONFIRMED 후보가 없습니다",
                created_at=now - timedelta(days=1),
            )
        )
        # P35: one TOO_LATE-excluded reading so risk_avoidance's exclusion
        # count is non-zero in the demo.
        session.add(
            OverheatScoreRow(
                symbol="DEMO-000660",
                observed_at=now - timedelta(hours=2),
                return_1d_pct=9.5,
                return_2d_pct=16.0,
                return_5d_pct=21.0,
                distance_from_signal_pct=9.0,
                gap_pct=1.0,
                volume_ratio=2.0,
                atr_extension=1.5,
                heat_score=100.0,
                status="TOO_LATE",
                created_at=now - timedelta(hours=2),
            )
        )
        # P38: today's premarket macro check so the 시장 탭's "해외 매크로"
        # card has a real-shaped reading instead of another "데이터 없음".
        session.add(
            MacroSnapshotRow(
                observed_at=now - timedelta(hours=1),
                sp500_change_pct=0.6,
                sox_change_pct=1.1,
                vix_level=14.2,
                oil_change_pct=-0.8,
                usdkrw_change_pct=-0.2,
                regime="RISK_ON",
                headline="DEMO-VIX 14.2, S&P500 +0.6%, SOX +1.1% - 우호적",
                created_at=now - timedelta(hours=1),
            )
        )
        await session.commit()

    async with session_scope() as session:
        await record_heartbeat(session, state=HealthState.HEALTHY, message="guardian nominal (demo)")

    print(
        "Seeded demo data: 2 recommendations, 1 position, 1 risk snapshot, 1 incident, "
        "21 BTC candles, 21 KOSPI candles, 2 daily decisions, 1 overheat reading, 1 macro snapshot."
    )
    print(f"Guardian heartbeat ({GUARDIAN_SERVICE}) recorded as HEALTHY.")


if __name__ == "__main__":
    asyncio.run(seed())
