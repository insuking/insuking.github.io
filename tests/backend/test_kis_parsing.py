"""Unit tests for KIS real-time WebSocket message parsing (no network)."""

from datetime import UTC, time

import pytest

from app.integrations.kis.fields import H0STASP0_FIELDS, H0STCNT0_FIELDS
from app.integrations.kis.parsing import (
    is_pingpong,
    is_realtime_data_message,
    parse_envelope,
    record_to_orderbook,
    record_to_trade,
)
from app.models.domain import OrderSide

pytestmark = pytest.mark.P3


def _synthetic_record(fields: list[str], overrides: dict[str, str]) -> dict[str, str]:
    return {name: overrides.get(name, f"v_{name}") for name in fields}


def _raw_for(tr_id: str, records: list[dict[str, str]]) -> str:
    fields = H0STCNT0_FIELDS if tr_id == "H0STCNT0" else H0STASP0_FIELDS
    lines = ["^".join(record[name] for name in fields) for record in records]
    return f"0|{tr_id}|{len(records)}|" + "\n".join(lines)


def test_is_realtime_data_message_detects_leading_flag_digit() -> None:
    assert is_realtime_data_message("0|H0STCNT0|1|foo")
    assert is_realtime_data_message("1|H0STCNT0|1|foo")
    assert not is_realtime_data_message('{"header":{"tr_id":"H0STCNT0"}}')
    assert not is_realtime_data_message("")


def test_is_pingpong_detects_control_message() -> None:
    assert is_pingpong('{"header":{"tr_id":"PINGPONG"}}')
    assert not is_pingpong('{"header":{"tr_id":"H0STCNT0"}}')


def test_parse_envelope_splits_flag_trid_count_and_fields() -> None:
    record = _synthetic_record(
        H0STCNT0_FIELDS,
        {"MKSC_SHRN_ISCD": "005930", "STCK_CNTG_HOUR": "093015", "STCK_PRPR": "71000"},
    )
    raw = _raw_for("H0STCNT0", [record])

    envelope = parse_envelope(raw)

    assert envelope.encrypted is False
    assert envelope.tr_id == "H0STCNT0"
    assert envelope.data_count == 1
    assert len(envelope.records) == 1
    assert envelope.records[0]["MKSC_SHRN_ISCD"] == "005930"
    assert envelope.records[0]["STCK_PRPR"] == "71000"


def test_parse_envelope_handles_multiple_records() -> None:
    records = [
        _synthetic_record(H0STCNT0_FIELDS, {"MKSC_SHRN_ISCD": "005930"}),
        _synthetic_record(H0STCNT0_FIELDS, {"MKSC_SHRN_ISCD": "000660"}),
    ]
    raw = _raw_for("H0STCNT0", records)

    envelope = parse_envelope(raw)

    assert envelope.data_count == 2
    assert [r["MKSC_SHRN_ISCD"] for r in envelope.records] == ["005930", "000660"]


def test_parse_envelope_rejects_malformed_message() -> None:
    with pytest.raises(ValueError, match="malformed"):
        parse_envelope("not-enough-pipe-parts")


def test_parse_envelope_rejects_unknown_tr_id() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        parse_envelope("0|H0UNKNOWN|1|a^b^c")


def test_record_to_trade_maps_symbol_price_time_and_volume() -> None:
    record = {
        "MKSC_SHRN_ISCD": "005930",
        "STCK_CNTG_HOUR": "093015",
        "STCK_PRPR": "71000",
        "CNTG_VOL": "10",
    }

    trade = record_to_trade(record)

    assert trade.symbol == "005930"
    assert trade.price == 71000.0
    assert trade.quantity == 10.0
    assert trade.side == OrderSide.BUY  # no CCLD_DVSN present -> defaults to BUY
    # 09:30:15 KST == 00:30:15 UTC
    assert trade.exchange_ts.astimezone(UTC).time() == time(0, 30, 15)


def test_record_to_trade_maps_sell_side() -> None:
    record = {
        "MKSC_SHRN_ISCD": "005930",
        "STCK_CNTG_HOUR": "093015",
        "STCK_PRPR": "71000",
        "CNTG_VOL": "10",
        "CCLD_DVSN": "1",
    }
    assert record_to_trade(record).side == OrderSide.SELL


def test_record_to_orderbook_maps_levels_and_drops_empty_ones() -> None:
    record = {name: "0" for name in H0STASP0_FIELDS}
    record.update(
        {
            "MKSC_SHRN_ISCD": "005930",
            "BSOP_HOUR": "093015",
            "ASKP1": "71100",
            "ASKP_RSQN1": "50",
            "BIDP1": "71000",
            "BIDP_RSQN1": "30",
        }
    )

    book = record_to_orderbook(record)

    assert book.symbol == "005930"
    assert len(book.asks) == 1
    assert book.asks[0].price == 71100.0
    assert book.asks[0].quantity == 50.0
    assert len(book.bids) == 1
    assert book.bids[0].price == 71000.0
    assert book.bids[0].quantity == 30.0
