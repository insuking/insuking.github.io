"""P23 persistence: write scan results to `securities`/`radar_scores`.

Flagged as a "fast-follow, not blocked on anything" since P23's own scan
orchestration was built (see `app/stock_radar/scan.py`'s module docstring
history) - the DB schema (`app/db/models.py`'s `SecurityRow`/
`RadarScoreRow`/`RadarFeatureRow`) has existed and been migrated since
P23, this module is the part that actually writes to it.

Scope: `securities` (upsert) and `radar_scores` (append one row per scored
symbol per run) only. `radar_scores.explanation`'s JSON blob also carries
`reference_close` (P27's `confirm_entry()` needs it, and `radar_scores`
has no dedicated price column - adding one would be a real schema change
for one value already available as JSON, not worth it here) alongside the
existing `max_available`/`positive`/`negative`. `radar_features` is
deliberately NOT written here -
`score_prebreakout()` only returns `ScoreFactor` entries for factors that
crossed a display threshold (positive/negative), not every raw feature
value `radar_features`' columns expect (e.g. `price_return_1d`,
`bollinger_width`) regardless of whether they were "notable" - writing
partial/zeroed rows there would be worse than not writing at all. Wiring
that up needs `score_prebreakout()` to return its raw intermediate values
too, which is a real but separate change from this one.

`market` is a single caller-supplied value applied to every symbol in one
call - the same simplification `KisRestClient.get_quote()` already uses
(see its own `market` parameter default). This project has no verified
per-symbol KOSPI/KOSDAQ classification yet (no KRX master-file
downloader - see `app/stock_radar/scan.py`'s module docstring), so mixing
KOSPI and KOSDAQ symbols in one call to this function will mislabel
whichever ones don't match `market`. Fine for `scripts/scan_stocks.py`'s
current KOSPI-only default universe; not fine once KOSDAQ symbols are
scanned in the same run - documented here rather than silently wrong.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RadarScoreRow, SecurityRow
from app.models.domain import Market
from app.stock_radar.scoring import PreBreakoutScore


async def persist_scan_results(
    session: AsyncSession,
    results: list[PreBreakoutScore],
    names: dict[str, str],
    market: Market = Market.KOSPI,
    scan_run_id: str | None = None,
) -> str:
    """Upserts one `SecurityRow` per symbol (creating it, or refreshing
    `name`/`market` if either changed) and appends one `RadarScoreRow` per
    result, ranked by `results`' existing order (already ranked by
    `rank_prebreakout_candidates()` - 1-indexed, matching how humans read
    "rank 1"). Returns the `scan_run_id` used (generated if not supplied)
    so a caller can later query every row this call wrote via
    `RadarScoreRow.scan_run_id`.
    """
    run_id = scan_run_id or str(uuid.uuid4())
    now = datetime.now(UTC)

    for rank, result in enumerate(results, start=1):
        name = names.get(result.symbol, result.symbol)
        existing = await session.get(SecurityRow, result.symbol)
        if existing is None:
            session.add(
                SecurityRow(
                    symbol=result.symbol,
                    name=name,
                    market=market.value,
                    data_updated_at=now,
                    created_at=now,
                )
            )
        else:
            if existing.name != name:
                existing.name = name
            if existing.market != market.value:
                existing.market = market.value
            existing.data_updated_at = now

        session.add(
            RadarScoreRow(
                symbol=result.symbol,
                scan_run_id=run_id,
                scored_at=now,
                prebreakout_score=result.total_score,
                rank=rank,
                model_version=result.model_version,
                explanation=json.dumps(
                    {
                        "max_available": result.max_available,
                        "reference_close": result.reference_close,
                        "positive": [asdict(f) for f in result.positive],
                        "negative": [asdict(f) for f in result.negative],
                    }
                ),
                created_at=now,
            )
        )

    await session.commit()
    return run_id


async def get_security_names(session: AsyncSession, symbols: list[str]) -> dict[str, str]:
    """symbol -> Korean name for whichever of `symbols` have a `SecurityRow`
    (P33) - written by this same module's `persist_scan_results()` above, so
    a symbol scored in the run that produced `symbols` always has one by the
    time this is called. A symbol somehow missing one is just omitted, not
    defaulted to something fabricated - callers fall back to the symbol
    itself for display.
    """
    if not symbols:
        return {}
    rows = (
        await session.execute(select(SecurityRow).where(SecurityRow.symbol.in_(symbols)))
    ).scalars().all()
    return {row.symbol: row.name for row in rows}


async def get_latest_scan(session: AsyncSession) -> list[RadarScoreRow]:
    """The most recent `scan_run_id`'s `RadarScoreRow` rows, ordered by
    rank - shared by `scripts/reconfirm_entries.py` (P27) and the
    `/api/stock-radar` read endpoint (P28) so both agree on "what counts
    as the latest scan" from one place rather than each running its own
    slightly-different query. Empty list, not an error, when no scan has
    ever run yet - the honest state of a fresh deployment.
    """
    latest_run_id = (
        await session.execute(select(RadarScoreRow.scan_run_id).order_by(RadarScoreRow.created_at.desc()).limit(1))
    ).scalar_one_or_none()
    if latest_run_id is None:
        return []
    rows = (
        await session.execute(
            select(RadarScoreRow).where(RadarScoreRow.scan_run_id == latest_run_id).order_by(RadarScoreRow.rank)
        )
    ).scalars().all()
    return list(rows)
