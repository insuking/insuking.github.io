#!/usr/bin/env python3
"""Bounded repeated-cycle stress run (P22).

This is explicitly NOT the 24h-minimum / 72h-target soak
docs/MASTER_SPEC.md's P22 acceptance calls for - that requires a real,
continuously-running deployment observed over real wall-clock days, which
an interactive development session cannot produce. Marking that item
"done" from a few minutes of cycling would be exactly the kind of
unverified COMPLETE claim the master spec's opening line forbids ("절대로
테스트하지 않은 기능을 COMPLETE라고 표시하지 않는다"). What this script
gives instead, honestly: N repeated cycles through the actually-running
parts of the system (DB/Redis health checks and reconnects, a full P19
self-healing recovery cycle, a full P20 paper-trade buy/sell cycle) against
real local Postgres/Redis, timing each cycle and watching this process's
own RSS, to catch a gross resource leak or crash under repetition before
it ever reaches a real multi-day soak. A clean run here is a precondition
for attempting the real soak, not a substitute for it - see
docs/RELEASE_READINESS.md.
"""

from __future__ import annotations

import argparse
import asyncio
import resource
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

sys.path.insert(0, ".")

from sqlalchemy import delete, select

from app.db.models import Incident, PaperAccount, PaperFill, PaperOrder, PaperPosition
from app.db.session import session_scope
from app.models.domain import HealthState
from app.paper_trading.cost_model import STOCK_COSTS
from app.paper_trading.fill_simulator import MarketSnapshot
from app.paper_trading.ledger import get_or_create_account, place_paper_order
from app.supervisor.failure_classifier import FailureType
from app.supervisor.health_monitor import check_database_health, check_redis_health
from app.supervisor.recovery_manager import handle_failure
from app.supervisor.service_restart import (
    restart_database_connection,
    restart_redis_connection,
)

_SERVICE_NAME = "soak-lite"
_PAPER_ACCOUNT_ID = "SOAK_LITE_PAPER"
_SNAPSHOT = MarketSnapshot(bid=99.0, ask=101.0, available_volume=1_000_000.0)


@dataclass
class CycleResult:
    cycle: int
    duration_seconds: float
    errors: list[str] = field(default_factory=list)


async def _recover_stub() -> bool:
    return True


async def _run_cycle(cycle: int) -> CycleResult:
    start = time.monotonic()
    errors: list[str] = []

    try:
        db_healthy = await check_database_health()
        if db_healthy.state != HealthState.HEALTHY:
            errors.append(f"database health check reported {db_healthy.state}")
    except Exception as exc:  # noqa: BLE001 - a cycle failure is data, not a crash
        errors.append(f"check_database_health raised: {exc!r}")

    try:
        redis_healthy = await check_redis_health()
        if redis_healthy.state != HealthState.HEALTHY:
            errors.append(f"redis health check reported {redis_healthy.state}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"check_redis_health raised: {exc!r}")

    try:
        if not await restart_database_connection():
            errors.append("restart_database_connection returned False")
        if not await restart_redis_connection():
            errors.append("restart_redis_connection returned False")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"reconnect cycle raised: {exc!r}")

    try:
        async with session_scope() as session:
            outcome = await handle_failure(
                session,
                service=_SERVICE_NAME,
                failure_type=FailureType.API_TIMEOUT,
                severity="LOW",
                recover=_recover_stub,
            )
        if outcome.resulting_state != HealthState.HEALTHY:
            errors.append(f"recovery cycle ended in {outcome.resulting_state}, not HEALTHY")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"recovery cycle raised: {exc!r}")

    try:
        async with session_scope() as session:
            await get_or_create_account(session, _PAPER_ACCOUNT_ID, "STOCK", starting_cash=10_000_000.0)
            symbol = f"SOAK-{cycle}"
            buy = await place_paper_order(
                session,
                account_id=_PAPER_ACCOUNT_ID,
                symbol=symbol,
                side="BUY",
                order_type="MARKET",
                quantity=1.0,
                limit_price=None,
                snapshot=_SNAPSHOT,
                costs=STOCK_COSTS,
            )
            if buy.order.status != "FILLED":
                errors.append(f"paper buy did not fill: {buy.order.status} ({buy.order.rejection_reason})")
            sell = await place_paper_order(
                session,
                account_id=_PAPER_ACCOUNT_ID,
                symbol=symbol,
                side="SELL",
                order_type="MARKET",
                quantity=1.0,
                limit_price=None,
                snapshot=_SNAPSHOT,
                costs=STOCK_COSTS,
            )
            if sell.order.status != "FILLED":
                errors.append(f"paper sell did not fill: {sell.order.status} ({sell.order.rejection_reason})")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"paper-trade cycle raised: {exc!r}")

    duration = time.monotonic() - start
    return CycleResult(cycle=cycle, duration_seconds=duration, errors=errors)


async def _cleanup() -> None:
    async with session_scope() as session:
        await session.execute(delete(Incident).where(Incident.service == _SERVICE_NAME))
        order_ids_result = await session.execute(
            select(PaperOrder.id).where(PaperOrder.account_id == _PAPER_ACCOUNT_ID)
        )
        order_ids = order_ids_result.scalars().all()
        if order_ids:
            await session.execute(delete(PaperFill).where(PaperFill.order_id.in_(order_ids)))
        await session.execute(delete(PaperOrder).where(PaperOrder.account_id == _PAPER_ACCOUNT_ID))
        await session.execute(delete(PaperPosition).where(PaperPosition.account_id == _PAPER_ACCOUNT_ID))
        await session.execute(delete(PaperAccount).where(PaperAccount.id == _PAPER_ACCOUNT_ID))
        await session.commit()


async def run(cycles: int, interval_seconds: float) -> tuple[list[CycleResult], int, int]:
    results: list[CycleResult] = []
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    for i in range(cycles):
        results.append(await _run_cycle(i))
        if i < cycles - 1:
            await asyncio.sleep(interval_seconds)
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    await _cleanup()
    return results, rss_before, rss_after


def _write_report(
    path: str, results: list[CycleResult], rss_before: int, rss_after: int, cycles: int, interval: float
) -> None:
    durations = [r.duration_seconds for r in results]
    total_errors = sum(len(r.errors) for r in results)
    lines = [
        "# Soak-lite run (P22)",
        "",
        f"Run at {datetime.now(UTC).isoformat()}",
        "",
        (
            "**This is a bounded repeated-cycle stress check, not the "
            "docs/MASTER_SPEC.md P22 24h-minimum / 72h-target soak.** See "
            "scripts/soak_lite.py's module docstring and docs/RELEASE_READINESS.md "
            "for what that real soak still requires."
        ),
        "",
        f"- Cycles: {cycles}",
        f"- Interval between cycles: {interval}s",
        f"- Total errors across all cycles: {total_errors}",
        (
            f"- Cycle duration (s): min={min(durations):.4f} max={max(durations):.4f} "
            f"mean={statistics.mean(durations):.4f} stdev={statistics.pstdev(durations):.4f}"
        ),
        f"- Process RSS (KB): before={rss_before} after={rss_after} delta={rss_after - rss_before}",
        "",
    ]
    if total_errors:
        lines.append("## Errors")
        for r in results:
            for err in r.errors:
                lines.append(f"- cycle {r.cycle}: {err}")
    else:
        lines.append("No errors across any cycle.")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--interval-seconds", type=float, default=0.5)
    parser.add_argument("--report", type=str, default="../docs/daily/SOAK_LITE.md")
    args = parser.parse_args()

    results, rss_before, rss_after = asyncio.run(run(args.cycles, args.interval_seconds))
    _write_report(args.report, results, rss_before, rss_after, args.cycles, args.interval_seconds)

    total_errors = sum(len(r.errors) for r in results)
    print(f"soak-lite: {args.cycles} cycles, {total_errors} errors, report at {args.report}")
    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
