"""KRX master-file parser tests (app/integrations/kis/krx_master.py).

No real network - `fetch_kospi_master()`/`fetch_kosdaq_master()` are tested
against `httpx.MockTransport` serving an in-memory zip built to the exact
byte layout documented in that module (independently re-derived here, not
imported from the module under test, so a bug in the module's own offset
constants can't make these tests pass by circular reasoning). The real
download host (`new.real.download.dws.co.kr`) is not reachable from this
sandbox - see `test_krx_master_integration.py` for the (skipped) real-
connection test and why.
"""

from __future__ import annotations

import io
import zipfile

import httpx
import pytest
from app.integrations.kis.krx_master import (
    fetch_kosdaq_master,
    fetch_kospi_master,
    rank_tradable_by_liquidity,
)

pytestmark = [pytest.mark.P30, pytest.mark.asyncio]

# Independently re-derived from koreainvestment/open-trading-api's
# stocks_info/kis_kospi_code_mst.py / kis_kosdaq_code_mst.py field_specs -
# see krx_master.py's own docstring for the full provenance.
_KOSPI_PART2_WIDTH = 227
_KOSPI_HALTED_OFFSET = 60
_KOSPI_ADMIN_OFFSET = 62
_KOSPI_ETP_OFFSET = 22
_KOSPI_VOLUME_OFFSET = 81
_KOSPI_VOLUME_WIDTH = 12

_KOSDAQ_PART2_WIDTH = 221
_KOSDAQ_HALTED_OFFSET = 55
_KOSDAQ_ADMIN_OFFSET = 57
_KOSDAQ_ETP_OFFSET = 18
_KOSDAQ_VOLUME_OFFSET = 76
_KOSDAQ_VOLUME_WIDTH = 12


def _build_line(
    symbol: str,
    name: str,
    *,
    part2_width: int,
    halted_offset: int,
    admin_offset: int,
    etp_offset: int,
    volume_offset: int,
    volume_width: int,
    halted: bool = False,
    administrative: bool = False,
    is_etp: bool = False,
    volume: int = 0,
) -> str:
    part1 = symbol.ljust(9) + "KR0000000000" + name.ljust(20)
    part2 = list(" " * part2_width)
    part2[halted_offset] = "1" if halted else "0"
    part2[admin_offset] = "1" if administrative else "0"
    part2[etp_offset] = "1" if is_etp else "0"
    volume_str = str(volume).rjust(volume_width)
    part2[volume_offset : volume_offset + volume_width] = list(volume_str)
    return part1 + "".join(part2)


def _zip_with_member(member_name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as archive:
        archive.writestr(member_name, text.encode("cp949"))
    return buf.getvalue()


def _mock_client(zip_bytes: bytes) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=zip_bytes)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_kospi_master_parses_symbol_name_and_flags() -> None:
    lines = [
        _build_line(
            "005930",
            "삼성전자",
            part2_width=_KOSPI_PART2_WIDTH,
            halted_offset=_KOSPI_HALTED_OFFSET,
            admin_offset=_KOSPI_ADMIN_OFFSET,
            etp_offset=_KOSPI_ETP_OFFSET,
            volume_offset=_KOSPI_VOLUME_OFFSET,
            volume_width=_KOSPI_VOLUME_WIDTH,
            volume=12_345_678,
        ),
        _build_line(
            "999999",
            "정지종목",
            part2_width=_KOSPI_PART2_WIDTH,
            halted_offset=_KOSPI_HALTED_OFFSET,
            admin_offset=_KOSPI_ADMIN_OFFSET,
            etp_offset=_KOSPI_ETP_OFFSET,
            volume_offset=_KOSPI_VOLUME_OFFSET,
            volume_width=_KOSPI_VOLUME_WIDTH,
            halted=True,
            volume=999,
        ),
        _build_line(
            "530090",
            "삼성 대만 선물 ETN(H)",
            part2_width=_KOSPI_PART2_WIDTH,
            halted_offset=_KOSPI_HALTED_OFFSET,
            admin_offset=_KOSPI_ADMIN_OFFSET,
            etp_offset=_KOSPI_ETP_OFFSET,
            volume_offset=_KOSPI_VOLUME_OFFSET,
            volume_width=_KOSPI_VOLUME_WIDTH,
            is_etp=True,
            volume=1_000_000,
        ),
    ]
    zip_bytes = _zip_with_member("kospi_code.mst", "\n".join(lines) + "\n")

    async with _mock_client(zip_bytes) as client:
        rows = await fetch_kospi_master(client)

    assert len(rows) == 3
    samsung = next(r for r in rows if r.symbol == "005930")
    assert samsung.name == "삼성전자"
    assert samsung.halted is False
    assert samsung.administrative is False
    assert samsung.is_etp is False
    assert samsung.prev_day_volume == 12_345_678.0

    halted = next(r for r in rows if r.symbol == "999999")
    assert halted.halted is True

    etn = next(r for r in rows if r.symbol == "530090")
    assert etn.is_etp is True


async def test_fetch_kosdaq_master_uses_its_own_byte_layout() -> None:
    line = _build_line(
        "247540",
        "에코프로비엠",
        part2_width=_KOSDAQ_PART2_WIDTH,
        halted_offset=_KOSDAQ_HALTED_OFFSET,
        admin_offset=_KOSDAQ_ADMIN_OFFSET,
        etp_offset=_KOSDAQ_ETP_OFFSET,
        volume_offset=_KOSDAQ_VOLUME_OFFSET,
        volume_width=_KOSDAQ_VOLUME_WIDTH,
        volume=5_000_000,
    )
    zip_bytes = _zip_with_member("kosdaq_code.mst", line + "\n")

    async with _mock_client(zip_bytes) as client:
        rows = await fetch_kosdaq_master(client)

    assert len(rows) == 1
    assert rows[0].symbol == "247540"
    assert rows[0].name == "에코프로비엠"
    assert rows[0].prev_day_volume == 5_000_000.0


async def test_fetch_master_skips_blank_lines() -> None:
    line = _build_line(
        "005930",
        "삼성전자",
        part2_width=_KOSPI_PART2_WIDTH,
        halted_offset=_KOSPI_HALTED_OFFSET,
        admin_offset=_KOSPI_ADMIN_OFFSET,
        etp_offset=_KOSPI_ETP_OFFSET,
        volume_offset=_KOSPI_VOLUME_OFFSET,
        volume_width=_KOSPI_VOLUME_WIDTH,
        volume=100,
    )
    zip_bytes = _zip_with_member("kospi_code.mst", "\n" + line + "\n\n")

    async with _mock_client(zip_bytes) as client:
        rows = await fetch_kospi_master(client)

    assert len(rows) == 1


def test_rank_tradable_by_liquidity_excludes_halted_and_administrative() -> None:
    from app.integrations.kis.krx_master import MasterRow

    rows = [
        MasterRow(symbol="A", name="a", halted=False, administrative=False, prev_day_volume=100.0),
        MasterRow(symbol="B", name="b", halted=True, administrative=False, prev_day_volume=999_999.0),
        MasterRow(symbol="C", name="c", halted=False, administrative=True, prev_day_volume=999_999.0),
        MasterRow(symbol="D", name="d", halted=False, administrative=False, prev_day_volume=5_000.0),
    ]

    ranked = rank_tradable_by_liquidity(rows, top_n=10)

    assert [r.symbol for r in ranked] == ["D", "A"]


@pytest.mark.P44
def test_rank_tradable_by_liquidity_excludes_etp_rows() -> None:
    """P44 - a real deployment run surfaced the full-universe rotation
    filling up with ETF/ETN codes ranked alongside real company stocks
    (they mechanically track an index and so look like a compressing/
    breaking-out "stock" to the scorer); ETP-flagged rows must never
    reach the scan universe, no matter how liquid."""
    from app.integrations.kis.krx_master import MasterRow

    rows = [
        MasterRow(symbol="STOCK", name="real company", halted=False, administrative=False, prev_day_volume=1_000.0),
        MasterRow(
            symbol="ETN",
            name="레버리지 ETN",
            halted=False,
            administrative=False,
            prev_day_volume=999_999_999.0,
            is_etp=True,
        ),
    ]

    ranked = rank_tradable_by_liquidity(rows, top_n=10)

    assert [r.symbol for r in ranked] == ["STOCK"]


def test_rank_tradable_by_liquidity_respects_top_n() -> None:
    from app.integrations.kis.krx_master import MasterRow

    rows = [
        MasterRow(symbol=str(i), name="x", halted=False, administrative=False, prev_day_volume=float(i))
        for i in range(10)
    ]

    ranked = rank_tradable_by_liquidity(rows, top_n=3)

    assert [r.symbol for r in ranked] == ["9", "8", "7"]
