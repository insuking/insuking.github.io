"""P34/P35 persistence: `regime_relative_strength` and `overheat_scores`.

Split from `app/stock_radar/persistence.py` (P23's `securities`/
`radar_scores` writer) rather than added to it - these two tables have
nothing to do with the securities master or the PRE-BREAKOUT score
itself, they're two new, independent signals (see
`app/stock_radar/regime_interaction.py` and `app/stock_radar/overheat.py`
for what each actually means), and keeping them in their own module
means a caller that only needs one doesn't have to import the other's
DB models.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OverheatScoreRow, RegimeRelativeStrengthRow
from app.stock_radar.overheat import HeatScore
from app.stock_radar.regime_interaction import InteractionScore


async def persist_interaction_score(
    session: AsyncSession,
    symbol: str,
    market_regime: str,
    benchmark_return_pct: float,
    stock_return_pct: float,
    foreign_net_today: float,
    institution_net_today: float,
    score: InteractionScore,
    observed_at: datetime | None = None,
) -> None:
    """Appends one row - `regime_relative_strength` is a history, not a
    latest-only table (see `RegimeRelativeStrengthRow`'s own docstring),
    same append-only shape as `persist_scan_results()`'s `radar_scores`
    writes. Does not commit - same convention as
    `app.stock_radar.persistence.persist_scan_results()`, so a caller can
    batch several of these plus other writes into one transaction.
    """
    session.add(
        RegimeRelativeStrengthRow(
            symbol=symbol,
            observed_at=observed_at or datetime.now(UTC),
            benchmark_return_pct=benchmark_return_pct,
            stock_return_pct=stock_return_pct,
            foreign_net_today=foreign_net_today,
            institution_net_today=institution_net_today,
            market_regime=market_regime,
            weak_market_resilience_score=score.weak_market_resilience_score,
            flow_resilience_score=score.flow_resilience_score,
            interaction_score=score.interaction_score,
            label=score.label.value,
            created_at=datetime.now(UTC),
        )
    )


async def upsert_heat_score(
    session: AsyncSession,
    symbol: str,
    score: HeatScore,
    observed_at: datetime | None = None,
) -> None:
    """`overheat_scores` is keyed `(symbol, observed_at)` - a later scan for
    the same symbol at the same `observed_at` (this project's own scans
    run at most once per real trading day, so `observed_at` is normally
    truncated to that day - see the caller) replaces the row rather than
    erroring or duplicating, via Postgres's `ON CONFLICT DO UPDATE`
    (`insert().on_conflict_do_update()`) - the same idempotent-replace
    intent `scan_crypto.py`/`reconfirm_entries.py` already apply at the
    application level for `Recommendation` rows, expressed here at the
    database level since the composite primary key makes that possible.
    Does not commit, same convention as `persist_interaction_score()`.
    """
    resolved_observed_at = observed_at or datetime.now(UTC)
    values = {
        "symbol": symbol,
        "observed_at": resolved_observed_at,
        "return_1d_pct": score.return_1d_pct,
        "return_2d_pct": score.return_2d_pct,
        "return_5d_pct": score.return_5d_pct,
        "distance_from_signal_pct": score.distance_from_signal_pct,
        "gap_pct": score.gap_pct,
        "volume_ratio": score.volume_ratio,
        "atr_extension": score.atr_extension,
        "heat_score": score.heat_score,
        "status": score.status.value,
        "created_at": datetime.now(UTC),
    }
    stmt = pg_insert(OverheatScoreRow).values(**values)
    update_cols = {k: v for k, v in values.items() if k not in ("symbol", "observed_at", "created_at")}
    stmt = stmt.on_conflict_do_update(index_elements=["symbol", "observed_at"], set_=update_cols)
    await session.execute(stmt)
