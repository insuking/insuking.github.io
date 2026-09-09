"""KRX 전종목 코드 마스터파일 다운로드/파싱 (KOSPI/KOSDAQ 전체 종목 유니버스).

`app/stock_radar/scan.py`'s `scan_stock_universe()` has always taken a
caller-supplied `symbols: list[str]` rather than pulling the real KOSPI/
KOSDAQ universe itself - `scripts/scan_stocks.py` defaulted to 5 hardcoded
large-cap names because "this project has no verified master-file parser
yet" (see that module's own docstring). This module is that parser.

**Not part of KIS's authenticated REST API** - `kospi_code.mst.zip`/
`kosdaq_code.mst.zip` are plain static files on a separate public download
host (`new.real.download.dws.co.kr`), no `appkey`/`appsecret`/`tr_id`
needed, unlike every other KIS integration in this project.

**Field layout provenance**: KIS's own public sample repo
(`koreainvestment/open-trading-api`, `stocks_info/kis_kospi_code_mst.py`
and `kis_kosdaq_code_mst.py`) was fetched directly (`curl` on the raw
GitHub content, not an AI-summarized paraphrase - a first WebFetch-based
summary of this same file mis-transcribed the `field_specs` width list,
caught only because the widths' sum didn't add up to the expected row
length; the raw source was fetched instead specifically to avoid trusting
that transcription). Each `.mst` line is `cp949`-encoded text: a
variable-length "part1" (`단축코드`/short code, `표준코드`/ISIN, `한글명`/
Korean name, comma-separated in the reference script but sliced by fixed
offset here) followed by a **fixed-width "part2"** whose total byte width
differs by market - 227 real data bytes for KOSPI (`row[-228:]` in the
reference script includes one trailing newline byte past the 70 defined
columns; the widths were independently summed here and cross-checked
against that 228 to catch the same class of transcription error) and 221
for KOSDAQ (`row[-222:]`, 64 columns). Only 4 of each market's columns are
parsed - `거래정지`(halted)/`관리종목`(administrative) as tradability
flags, and `전일거래량`(previous-day volume) as the liquidity-ranking
signal `scripts/scan_stocks.py` uses to pick a real top-N universe instead
of scanning every listed symbol (KOSPI+KOSDAQ combined runs well into the
thousands - not viable against KIS's confirmed ~2 req/sec rate limit for
the per-symbol daily-price/investor-flow calls `scan_stock_universe()`
already makes). `시가총액`(market cap) is deliberately NOT used for
cross-market ranking - KOSPI's column has no stated unit in the reference
script while KOSDAQ's is explicitly "(억)", and this project won't compare
two differently-united numbers without confirming they match; volume is
selected per-market only, never merged into one cross-market sort, so this
question doesn't need answering to make the ranking correct.

**BLOCKED, not verified against a live response**: `new.real.download.dws.co.kr`
is not reachable from this development sandbox (egress policy denies the
CONNECT, same class of restriction as this session's Docker Hub pulls -
see `tests/backend/test_krx_master_integration.py`, which is skipped for
exactly this reason). The offsets above were computed by mechanically
pairing the reference scripts' own `field_specs`/column-name lists in
order (not eyeballed), so they're evidence-based, not guessed - but they
have not been proven against a real KIS-hosted file the way this
project's other KIS integrations were proven against real credentials.
Re-verify against a real download the first time this runs somewhere with
real network access; `tests/backend/test_krx_master.py`'s synthetic-zip
fixture tests are built to the same byte layout and will keep passing
either way, so they can't catch a real-world drift on their own.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

import httpx

KOSPI_MASTER_URL = "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip"
KOSDAQ_MASTER_URL = "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip"

_KOSPI_MEMBER_NAME = "kospi_code.mst"
_KOSDAQ_MEMBER_NAME = "kosdaq_code.mst"

# Part1 slicing matches the reference scripts' rf1_1/rf1_3 exactly:
# row[0:9].rstrip() (단축코드) and row[21:].strip() (한글명) - rf1_2
# (표준코드/ISIN, row[9:21]) isn't kept, this project has no use for it yet.
_SYMBOL_END = 9
_NAME_START = 21

# (part2 byte width excluding the trailing newline, halted-flag offset,
# administrative-flag offset, (prev-day-volume offset, width)) - see this
# module's own docstring for how each of these was derived.
_KOSPI_LAYOUT = (227, 60, 62, (81, 12))
_KOSDAQ_LAYOUT = (221, 55, 57, (76, 12))


@dataclass
class MasterRow:
    symbol: str
    name: str
    halted: bool
    administrative: bool
    prev_day_volume: float


def _parse_flag(raw: str) -> bool:
    return raw.strip() in ("1", "Y")


def _parse_master_text(
    text: str, part2_width: int, halted_offset: int, administrative_offset: int, volume_offset_width: tuple[int, int]
) -> list[MasterRow]:
    vol_start, vol_width = volume_offset_width
    rows: list[MasterRow] = []
    for line in text.splitlines():
        if len(line) < part2_width:
            continue
        part1 = line[: len(line) - part2_width]
        part2 = line[-part2_width:]
        symbol = part1[:_SYMBOL_END].strip()
        if not symbol:
            continue
        name = part1[_NAME_START:].strip()
        halted = _parse_flag(part2[halted_offset : halted_offset + 1])
        administrative = _parse_flag(part2[administrative_offset : administrative_offset + 1])
        volume_raw = part2[vol_start : vol_start + vol_width].strip()
        try:
            prev_day_volume = float(volume_raw) if volume_raw else 0.0
        except ValueError:
            prev_day_volume = 0.0
        rows.append(
            MasterRow(
                symbol=symbol,
                name=name,
                halted=halted,
                administrative=administrative,
                prev_day_volume=prev_day_volume,
            )
        )
    return rows


def _extract_member(zip_bytes: bytes, member_name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        return archive.read(member_name).decode("cp949")


async def fetch_kospi_master(client: httpx.AsyncClient) -> list[MasterRow]:
    response = await client.get(KOSPI_MASTER_URL)
    response.raise_for_status()
    text = _extract_member(response.content, _KOSPI_MEMBER_NAME)
    width, halted_off, admin_off, vol = _KOSPI_LAYOUT
    return _parse_master_text(text, width, halted_off, admin_off, vol)


async def fetch_kosdaq_master(client: httpx.AsyncClient) -> list[MasterRow]:
    response = await client.get(KOSDAQ_MASTER_URL)
    response.raise_for_status()
    text = _extract_member(response.content, _KOSDAQ_MEMBER_NAME)
    width, halted_off, admin_off, vol = _KOSDAQ_LAYOUT
    return _parse_master_text(text, width, halted_off, admin_off, vol)


def rank_tradable_by_liquidity(rows: list[MasterRow], top_n: int) -> list[MasterRow]:
    """Excludes halted/administrative-designated symbols (per docs/
    MASTER_SPEC.md's general quality bar against recommending low-quality
    setups - the same instinct as crypto's pump-risk filtering, applied
    here to KIS's own tradability flags), then returns the `top_n` by
    previous-day volume, descending."""
    tradable = [r for r in rows if not r.halted and not r.administrative]
    return sorted(tradable, key=lambda r: r.prev_day_volume, reverse=True)[:top_n]
