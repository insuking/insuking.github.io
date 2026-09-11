import pytest

from app.radar.ranking import rank_candidates

pytestmark = pytest.mark.P4


def test_rank_candidates_slices_into_200_30_5() -> None:
    universe = [(f"SYM{i:04d}", float(i)) for i in range(250)]

    funnel = rank_candidates(universe)

    assert len(funnel.top200) == 200
    assert len(funnel.top30) == 30
    assert len(funnel.top5) == 5


def test_rank_candidates_orders_by_score_descending() -> None:
    universe = [("A", 10.0), ("B", 50.0), ("C", 30.0)]

    funnel = rank_candidates(universe)

    assert [c.symbol for c in funnel.top200] == ["B", "C", "A"]
    assert funnel.top5[0].score == 50.0


def test_rank_candidates_ties_break_by_symbol() -> None:
    universe = [("Z", 10.0), ("A", 10.0), ("M", 10.0)]

    funnel = rank_candidates(universe)

    assert [c.symbol for c in funnel.top200] == ["A", "M", "Z"]


def test_rank_candidates_handles_fewer_than_200() -> None:
    universe = [("A", 1.0), ("B", 2.0)]

    funnel = rank_candidates(universe)

    assert len(funnel.top200) == 2
    assert len(funnel.top30) == 2
    assert len(funnel.top5) == 2
