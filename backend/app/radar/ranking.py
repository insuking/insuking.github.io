"""TOP200 / TOP30 / TOP5 ranking funnel (P4)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RankedCandidate:
    symbol: str
    score: float


@dataclass
class RadarFunnel:
    top200: list[RankedCandidate]
    top30: list[RankedCandidate]
    top5: list[RankedCandidate]


def rank_candidates(scored: list[tuple[str, float]]) -> RadarFunnel:
    """Sort a universe by score (descending) and slice it into the three tiers.

    Ties break by symbol so the ordering is deterministic and test-stable.
    """
    ranked = [
        RankedCandidate(symbol=symbol, score=score)
        for symbol, score in sorted(scored, key=lambda item: (-item[1], item[0]))
    ]
    return RadarFunnel(top200=ranked[:200], top30=ranked[:30], top5=ranked[:5])
