"""P39: scripts/scan_stocks.py's own `_full_universe_symbols()` rotation
wiring - imported directly the same way `test_reconfirm_entries_decision.py`
already imports script-level functions from `scripts.reconfirm_entries`.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from datetime import UTC, datetime

import pytest

from app.integrations.kis.krx_master import MasterRow
from scripts import scan_stocks

pytestmark = pytest.mark.P39


def _rows(prefix: str, count: int) -> list[MasterRow]:
    return [
        MasterRow(symbol=f"{prefix}{i:04d}", name=f"{prefix}종목{i}", halted=False, administrative=False,
                   prev_day_volume=float(count - i))
        for i in range(count)
    ]


async def test_full_universe_symbols_returns_a_chunk_from_each_market(monkeypatch: pytest.MonkeyPatch) -> None:
    kospi_rows = _rows("K", 20)
    kosdaq_rows = _rows("Q", 15)

    async def _fake_kospi(client: object) -> list[MasterRow]:
        return kospi_rows

    async def _fake_kosdaq(client: object) -> list[MasterRow]:
        return kosdaq_rows

    monkeypatch.setattr(scan_stocks, "fetch_kospi_master", _fake_kospi)
    monkeypatch.setattr(scan_stocks, "fetch_kosdaq_master", _fake_kosdaq)

    now = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    symbols = await scan_stocks._full_universe_symbols(chunk_size_per_market=5, now=now, interval_seconds=1800)

    kospi_symbols = [s for s in symbols if s.startswith("K")]
    kosdaq_symbols = [s for s in symbols if s.startswith("Q")]
    assert len(kospi_symbols) == 5
    assert len(kosdaq_symbols) == 5


async def test_full_universe_symbols_excludes_halted_and_administrative(monkeypatch: pytest.MonkeyPatch) -> None:
    kospi_rows = [
        MasterRow(symbol="K0001", name="정상", halted=False, administrative=False, prev_day_volume=100.0),
        MasterRow(symbol="K0002", name="거래정지", halted=True, administrative=False, prev_day_volume=200.0),
        MasterRow(symbol="K0003", name="관리종목", halted=False, administrative=True, prev_day_volume=300.0),
    ]

    async def _fake_kospi(client: object) -> list[MasterRow]:
        return kospi_rows

    async def _fake_kosdaq(client: object) -> list[MasterRow]:
        return []

    monkeypatch.setattr(scan_stocks, "fetch_kospi_master", _fake_kospi)
    monkeypatch.setattr(scan_stocks, "fetch_kosdaq_master", _fake_kosdaq)

    now = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    symbols = await scan_stocks._full_universe_symbols(chunk_size_per_market=10, now=now, interval_seconds=1800)

    assert symbols == ["K0001"]


async def test_full_universe_symbols_advances_to_a_different_chunk_over_time(monkeypatch: pytest.MonkeyPatch) -> None:
    kospi_rows = _rows("K", 20)

    async def _fake_kospi(client: object) -> list[MasterRow]:
        return kospi_rows

    async def _fake_kosdaq(client: object) -> list[MasterRow]:
        return []

    monkeypatch.setattr(scan_stocks, "fetch_kospi_master", _fake_kospi)
    monkeypatch.setattr(scan_stocks, "fetch_kosdaq_master", _fake_kosdaq)

    interval = 1800
    first_now = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    second_now = datetime.fromtimestamp(first_now.timestamp() + interval, tz=UTC)

    first_symbols = await scan_stocks._full_universe_symbols(
        chunk_size_per_market=5, now=first_now, interval_seconds=interval
    )
    second_symbols = await scan_stocks._full_universe_symbols(
        chunk_size_per_market=5, now=second_now, interval_seconds=interval
    )

    assert first_symbols != second_symbols
