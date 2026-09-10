"""P39: pure tests for app.radar.universe_rotation.select_rotation_chunk."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.radar.universe_rotation import select_rotation_chunk

pytestmark = pytest.mark.P39


def test_empty_items_returns_empty_chunk() -> None:
    assert select_rotation_chunk([], chunk_size=10, now=datetime.now(UTC), interval_seconds=1800) == []


def test_non_positive_chunk_size_returns_empty_chunk() -> None:
    items = [1, 2, 3]
    assert select_rotation_chunk(items, chunk_size=0, now=datetime.now(UTC), interval_seconds=1800) == []
    assert select_rotation_chunk(items, chunk_size=-1, now=datetime.now(UTC), interval_seconds=1800) == []


def test_non_positive_interval_returns_empty_chunk() -> None:
    items = [1, 2, 3]
    assert select_rotation_chunk(items, chunk_size=2, now=datetime.now(UTC), interval_seconds=0) == []


def test_chunk_larger_than_items_returns_everything() -> None:
    items = list(range(5))
    result = select_rotation_chunk(items, chunk_size=100, now=datetime.now(UTC), interval_seconds=1800)
    assert result == items


def test_successive_time_slots_advance_through_every_chunk() -> None:
    items = list(range(10))  # chunk_size=3 -> chunks: [0,1,2] [3,4,5] [6,7,8] [9]
    interval = 1800
    base = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)

    seen: list[list[int]] = []
    for i in range(4):
        now = datetime.fromtimestamp(base.timestamp() + i * interval, tz=UTC)
        seen.append(select_rotation_chunk(items, chunk_size=3, now=now, interval_seconds=interval))

    assert seen[0] == [0, 1, 2]
    assert seen[1] == [3, 4, 5]
    assert seen[2] == [6, 7, 8]
    assert seen[3] == [9]


def test_rotation_wraps_back_to_the_start_after_the_last_chunk() -> None:
    items = list(range(10))
    interval = 1800
    base = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)

    # 4 chunks total (10 items / chunk_size 3, ceil -> 4); slot 4 should
    # wrap back to chunk 0.
    now = datetime.fromtimestamp(base.timestamp() + 4 * interval, tz=UTC)
    assert select_rotation_chunk(items, chunk_size=3, now=now, interval_seconds=interval) == [0, 1, 2]


def test_same_time_slot_is_deterministic_across_calls() -> None:
    items = list(range(20))
    now = datetime(2026, 9, 10, 12, 34, tzinfo=UTC)
    first = select_rotation_chunk(items, chunk_size=7, now=now, interval_seconds=1800)
    second = select_rotation_chunk(items, chunk_size=7, now=now, interval_seconds=1800)
    assert first == second


def test_every_item_is_covered_across_one_full_rotation() -> None:
    items = list(range(37))
    chunk_size = 6
    interval = 1800
    base = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
    num_chunks = 7  # ceil(37 / 6)

    covered: set[int] = set()
    for i in range(num_chunks):
        now = datetime.fromtimestamp(base.timestamp() + i * interval, tz=UTC)
        covered.update(select_rotation_chunk(items, chunk_size=chunk_size, now=now, interval_seconds=interval))

    assert covered == set(items)
