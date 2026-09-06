"""Parsing for KIS's real-time WebSocket wire format.

Verified envelope/framing against the official sample (`examples_user/
kis_auth.py` in koreainvestment/open-trading-api):

- A raw text frame is a real-time data message iff its first character is
  '0' (unencrypted) or '1' (encrypted, AES-256 - not implemented here since
  neither H0STCNT0 nor H0STASP0 uses it); anything else is a JSON control
  message (subscribe ack, PINGPONG).
- Data message shape: `{flag}|{tr_id}|{data_cnt}|{data_body}`.
- `data_body` holds `data_cnt` records separated by newlines, each record's
  fields separated by `^`, in the tr_id-specific order from `fields.py`.
- PINGPONG control messages must be echoed back verbatim to keep the
  connection alive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from app.integrations.kis.fields import H0STASP0_FIELDS, H0STCNT0_FIELDS
from app.models.domain import AssetType, OrderBook, OrderBookLevel, OrderSide, Trade

KST = timezone(timedelta(hours=9))


@dataclass
class ParsedEnvelope:
    encrypted: bool
    tr_id: str
    data_count: int
    records: list[dict[str, str]]


def is_realtime_data_message(raw: str) -> bool:
    return bool(raw) and raw[0] in ("0", "1")


def is_pingpong(raw: str) -> bool:
    return '"tr_id":"PINGPONG"' in raw.replace(" ", "")


def parse_envelope(raw: str) -> ParsedEnvelope:
    parts = raw.split("|")
    if len(parts) < 4:
        raise ValueError(f"malformed KIS realtime message (expected 4 '|'-parts): {raw!r}")

    flag, tr_id, count_str, data_body = parts[0], parts[1], parts[2], parts[3]
    field_names = _fields_for(tr_id)
    records = []
    for line in data_body.split("\n"):
        if not line:
            continue
        values = line.split("^")
        records.append(dict(zip(field_names, values, strict=False)))

    return ParsedEnvelope(
        encrypted=flag == "1", tr_id=tr_id, data_count=int(count_str), records=records
    )


def _fields_for(tr_id: str) -> list[str]:
    if tr_id == "H0STCNT0":
        return H0STCNT0_FIELDS
    if tr_id == "H0STASP0":
        return H0STASP0_FIELDS
    raise ValueError(f"unsupported KIS tr_id for parsing: {tr_id}")


def _hhmmss_to_utc(hhmmss: str, on: date) -> datetime:
    """KIS reports trade/quote time as HHMMSS in KST with no date - anchor to today."""
    hour, minute, second = int(hhmmss[0:2]), int(hhmmss[2:4]), int(hhmmss[4:6])
    kst_dt = datetime(on.year, on.month, on.day, hour, minute, second, tzinfo=KST)
    return kst_dt.astimezone(UTC)


def record_to_trade(record: dict[str, str]) -> Trade:
    received_ts = datetime.now(UTC)
    exchange_ts = _hhmmss_to_utc(record["STCK_CNTG_HOUR"], received_ts.date())
    return Trade(
        symbol=record["MKSC_SHRN_ISCD"],
        asset_type=AssetType.STOCK,
        price=float(record["STCK_PRPR"]),
        quantity=float(record["CNTG_VOL"]),
        # KIS doesn't carry an explicit trade-side flag in this feed; CCLD_DVSN
        # (1=매도/sell, 2=매수/buy) is the closest signal but isn't present on
        # every payload variant, so default to BUY rather than guess wrong.
        side=OrderSide.SELL if record.get("CCLD_DVSN") == "1" else OrderSide.BUY,
        exchange_ts=exchange_ts,
        received_ts=received_ts,
    )


def record_to_orderbook(record: dict[str, str]) -> OrderBook:
    received_ts = datetime.now(UTC)
    exchange_ts = _hhmmss_to_utc(record["BSOP_HOUR"], received_ts.date())

    asks = [
        OrderBookLevel(price=float(record[f"ASKP{i}"]), quantity=float(record[f"ASKP_RSQN{i}"]))
        for i in range(1, 11)
        if float(record[f"ASKP{i}"]) > 0
    ]
    bids = [
        OrderBookLevel(price=float(record[f"BIDP{i}"]), quantity=float(record[f"BIDP_RSQN{i}"]))
        for i in range(1, 11)
        if float(record[f"BIDP{i}"]) > 0
    ]

    return OrderBook(
        symbol=record["MKSC_SHRN_ISCD"],
        bids=bids,
        asks=asks,
        exchange_ts=exchange_ts,
        received_ts=received_ts,
    )
