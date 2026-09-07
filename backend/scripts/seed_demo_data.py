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

from app.db.models import Candle, Incident, Position, Recommendation, RiskStateRow
from app.db.session import session_scope
from app.guardian.health import SERVICE_NAME as GUARDIAN_SERVICE
from app.guardian.health import record_heartbeat
from app.models.domain import HealthState

_DEMO_SYMBOL = "KRW-BTC"


async def _clear_previous() -> None:
    async with session_scope() as session:
        await session.execute(delete(Recommendation).where(Recommendation.id.like("demo-%")))
        await session.execute(delete(Position).where(Position.id.like("demo-%")))
        await session.execute(delete(RiskStateRow).where(RiskStateRow.id.like("demo-%")))
        await session.execute(delete(Incident).where(Incident.id.like("demo-%")))
        await session.execute(delete(Candle).where(Candle.id.like("demo-%")))
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
        await session.commit()

    async with session_scope() as session:
        await record_heartbeat(session, state=HealthState.HEALTHY, message="guardian nominal (demo)")

    print("Seeded demo data: 2 recommendations, 1 position, 1 risk snapshot, 1 incident, 21 BTC candles.")
    print(f"Guardian heartbeat ({GUARDIAN_SERVICE}) recorded as HEALTHY.")


if __name__ == "__main__":
    asyncio.run(seed())
