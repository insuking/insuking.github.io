"""P36: `scripts/reconfirm_entries.py`'s own entry-filter proxy and
daily-decision picking logic - imported directly the same way
`test_scheduler.py` already imports script-level functions from
`scripts.scan_crypto`/`scripts.scan_stocks`/`scripts.reconfirm_entries`.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

import pytest

from app.stock_radar.scoring import (
    SCORE_MAX_AVAILABLE,
    SCORE_MAX_WITH_INSTITUTIONAL_FLOW,
    PreBreakoutScore,
    ScoreFactor,
)
from scripts.reconfirm_entries import _entry_filters

pytestmark = pytest.mark.P36


def _score(**overrides: object) -> PreBreakoutScore:
    defaults: dict[str, object] = {
        "symbol": "005930",
        "total_score": 40.0,
        "max_available": SCORE_MAX_AVAILABLE,
        "reference_close": 100.0,
        "positive": [],
        "negative": [],
    }
    defaults.update(overrides)
    return PreBreakoutScore(**defaults)  # type: ignore[arg-type]


def test_filters_total_is_seven_without_institutional_flow() -> None:
    _, total = _entry_filters(_score(max_available=SCORE_MAX_AVAILABLE))
    assert total == 7


def test_filters_total_is_eight_with_institutional_flow() -> None:
    _, total = _entry_filters(_score(max_available=SCORE_MAX_WITH_INSTITUTIONAL_FLOW))
    assert total == 8


def test_filters_passed_counts_the_positive_factor_list() -> None:
    score = _score(
        positive=[
            ScoreFactor("box_compression", 10.0, "압축"),
            ScoreFactor("obv_rising", 5.0, "OBV 상승"),
        ]
    )
    passed, _ = _entry_filters(score)
    assert passed == 2


def test_filters_passed_is_zero_with_no_positive_factors() -> None:
    passed, _ = _entry_filters(_score(positive=[]))
    assert passed == 0
