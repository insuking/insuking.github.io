from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.scheduler.market_hours import KST, is_krx_trading_hours

pytestmark = pytest.mark.P32


def _kst(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=KST)


def test_true_mid_session_on_a_weekday() -> None:
    assert is_krx_trading_hours(_kst(2026, 9, 9, 12, 0))  # 2026-09-09 is a Wednesday


def test_true_exactly_at_open() -> None:
    assert is_krx_trading_hours(_kst(2026, 9, 9, 9, 0))


def test_true_exactly_at_close() -> None:
    assert is_krx_trading_hours(_kst(2026, 9, 9, 15, 30))


def test_false_one_minute_before_open() -> None:
    assert not is_krx_trading_hours(_kst(2026, 9, 9, 8, 59))


def test_false_one_minute_after_close() -> None:
    assert not is_krx_trading_hours(_kst(2026, 9, 9, 15, 31))


def test_false_overnight() -> None:
    assert not is_krx_trading_hours(_kst(2026, 9, 9, 2, 0))


def test_false_on_saturday() -> None:
    assert not is_krx_trading_hours(_kst(2026, 9, 12, 12, 0))  # Saturday


def test_false_on_sunday() -> None:
    assert not is_krx_trading_hours(_kst(2026, 9, 13, 12, 0))  # Sunday


def test_converts_from_utc() -> None:
    # 2026-09-09 03:00 UTC == 2026-09-09 12:00 KST (a Wednesday) - a naive
    # `datetime.now(UTC)` call (this project's own convention elsewhere)
    # must still land inside the session correctly once converted.
    assert is_krx_trading_hours(datetime(2026, 9, 9, 3, 0, tzinfo=UTC))


def test_converts_from_other_timezone_across_the_date_line() -> None:
    # 2026-09-09 16:00 PDT (UTC-7) == 2026-09-10 08:00 KST - a day later on
    # the calendar and still before the 09:00 open. A naive local-time bug
    # here would silently compare the wrong calendar day/hour.
    la_time = datetime(2026, 9, 9, 16, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert not is_krx_trading_hours(la_time)


def test_naive_datetime_is_treated_as_utc() -> None:
    # No tzinfo at all - 03:00 naive treated as UTC == 12:00 KST, in session.
    assert is_krx_trading_hours(datetime(2026, 9, 9, 3, 0))  # noqa: DTZ001 - deliberately naive
