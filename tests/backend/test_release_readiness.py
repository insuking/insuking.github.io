"""P22 acceptance.

Two things, both actually exercised rather than merely asserted to exist
(docs/MASTER_SPEC.md's "never mark untested functionality as COMPLETE"
applies to P22 itself, not just the phases before it):

1. `docs/RELEASE_READINESS.md` declares one of the four states
   docs/MASTER_SPEC.md's P22 acceptance names, and reaffirms `LIVE_AUTO`
   stays disabled regardless.
2. `scripts/soak_lite.py`'s `run()` actually completes a real bounded
   cycle against local Postgres/Redis with zero errors - the same function
   the real soak-lite run in docs/daily/SOAK_LITE.md used, not a stub.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.models import Incident, PaperAccount, PaperFill, PaperOrder, PaperPosition
from app.db.session import session_scope

pytestmark = pytest.mark.P22

_VALID_FINAL_STATES = ("MONITOR READY", "PAPER READY", "LIVE_APPROVAL READY", "BLOCKED")
_REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(_REPO_ROOT / "backend"))
from scripts.soak_lite import _PAPER_ACCOUNT_ID, _SERVICE_NAME, run


def _read_release_readiness() -> str:
    path = _REPO_ROOT / "docs" / "RELEASE_READINESS.md"
    assert path.exists(), f"{path} does not exist - P22 must produce this file"
    return path.read_text()


def test_release_readiness_declares_exactly_one_valid_final_state() -> None:
    text = _read_release_readiness()
    # Only the "## Final state: ..." heading counts as the declaration -
    # the checklist tables legitimately use e.g. "**BLOCKED**" to describe
    # individual line items without that being the overall verdict.
    heading_line = next((line for line in text.splitlines() if line.startswith("## Final state:")), None)
    assert heading_line is not None, "no '## Final state: ...' heading found"
    declared = [state for state in _VALID_FINAL_STATES if state in heading_line]
    assert len(declared) == 1, f"expected exactly one valid final state in {heading_line!r}, found {declared}"


def test_release_readiness_reaffirms_live_auto_stays_disabled() -> None:
    text = _read_release_readiness()
    assert "LIVE_AUTO" in text
    assert "disabled" in text.lower() or "DISABLED" in text


def test_release_readiness_names_the_blocked_external_integrations() -> None:
    text = _read_release_readiness()
    for name in ("KIS", "Toss", "Upbit", "Kakao"):
        assert name in text, f"{name} should be named among the BLOCKED real-connection gaps"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        await session.execute(delete(Incident).where(Incident.service == _SERVICE_NAME))
        order_ids = (
            (await session.execute(select(PaperOrder.id).where(PaperOrder.account_id == _PAPER_ACCOUNT_ID)))
            .scalars()
            .all()
        )
        if order_ids:
            await session.execute(delete(PaperFill).where(PaperFill.order_id.in_(order_ids)))
        await session.execute(delete(PaperOrder).where(PaperOrder.account_id == _PAPER_ACCOUNT_ID))
        await session.execute(delete(PaperPosition).where(PaperPosition.account_id == _PAPER_ACCOUNT_ID))
        await session.execute(delete(PaperAccount).where(PaperAccount.id == _PAPER_ACCOUNT_ID))
        await session.commit()


@pytest.mark.asyncio
async def test_soak_lite_run_completes_bounded_cycles_with_no_errors() -> None:
    results, rss_before, rss_after = await run(cycles=2, interval_seconds=0.0)

    assert len(results) == 2
    for result in results:
        assert result.errors == [], f"cycle {result.cycle} had errors: {result.errors}"
    assert rss_before > 0
    assert rss_after > 0
