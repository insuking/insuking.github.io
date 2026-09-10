from datetime import UTC, date, datetime

import pytest

from scripts import reconfirm_entries, scan_crypto, scan_macro, scan_stocks
from scripts.scheduler import run_cycle

pytestmark = pytest.mark.P32

# A real Wednesday, mid-session KST (12:00 KST == 03:00 UTC).
_TRADING_HOURS_NOW = datetime(2026, 9, 9, 3, 0, tzinfo=UTC)
# Same Wednesday, well outside the 09:00-15:30 KST session.
_AFTER_HOURS_NOW = datetime(2026, 9, 9, 14, 0, tzinfo=UTC)  # 23:00 KST
# Both instants above fall on this KST calendar date - passing it as
# `last_macro_run_date` means "already ran today," so tests that aren't
# specifically about the macro pass don't trip it as a side effect.
_SAME_KST_DATE = date(2026, 9, 9)
# Before 08:20 KST on that same Wednesday (08:00 KST == 23:00 UTC the day before).
_BEFORE_MACRO_TIME_NOW = datetime(2026, 9, 8, 23, 0, tzinfo=UTC)  # 08:00 KST


def _calls(monkeypatch: pytest.MonkeyPatch, module: object, log: list[str], label: str, *, raises: bool = False) -> None:
    async def _fake() -> None:
        log.append(label)
        if raises:
            raise RuntimeError(f"{label} exploded")

    monkeypatch.setattr(module, "run", _fake)


async def test_crypto_scan_always_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")
    _calls(monkeypatch, scan_macro, log, "macro")

    await run_cycle(_AFTER_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE)

    assert log == ["crypto"]


async def test_stock_pass_runs_when_in_trading_hours_and_never_run_before(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")
    _calls(monkeypatch, scan_macro, log, "macro")

    ran_stock, _ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_stock is True
    assert log == ["crypto", "stock_scan", "reconfirm"]


async def test_stock_pass_skipped_outside_trading_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")
    _calls(monkeypatch, scan_macro, log, "macro")

    ran_stock, _ran_macro = await run_cycle(
        _AFTER_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_stock is False
    assert log == ["crypto"]


async def test_stock_pass_skipped_when_run_too_recently(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")
    _calls(monkeypatch, scan_macro, log, "macro")

    ran_stock, _ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=60.0, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_stock is False
    assert log == ["crypto"]


async def test_stock_pass_runs_again_once_the_interval_has_elapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")
    _calls(monkeypatch, scan_macro, log, "macro")

    ran_stock, _ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=1_800.0, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_stock is True
    assert log == ["crypto", "stock_scan", "reconfirm"]


async def test_a_failing_crypto_scan_does_not_block_the_stock_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto", raises=True)
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")
    _calls(monkeypatch, scan_macro, log, "macro")

    ran_stock, _ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_stock is True
    assert log == ["crypto", "stock_scan", "reconfirm"]


async def test_a_failing_stock_scan_does_not_prevent_reconfirm_from_still_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan", raises=True)
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")
    _calls(monkeypatch, scan_macro, log, "macro")

    ran_stock, _ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_stock is True
    assert log == ["crypto", "stock_scan", "reconfirm"]


async def test_macro_pass_runs_at_or_after_0820_kst_when_not_yet_run_today(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")
    _calls(monkeypatch, scan_macro, log, "macro")

    _ran_stock, ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=None
    )

    assert ran_macro is True
    assert "macro" in log


async def test_macro_pass_skipped_before_0820_kst(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")
    _calls(monkeypatch, scan_macro, log, "macro")

    _ran_stock, ran_macro = await run_cycle(
        _BEFORE_MACRO_TIME_NOW, seconds_since_last_stock_run=None, last_macro_run_date=None
    )

    assert ran_macro is False
    assert "macro" not in log


async def test_macro_pass_skipped_when_already_run_today(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")
    _calls(monkeypatch, scan_macro, log, "macro")

    _ran_stock, ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_macro is False
    assert "macro" not in log


async def test_macro_pass_runs_again_the_next_kst_calendar_date(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")
    _calls(monkeypatch, scan_macro, log, "macro")

    yesterday = date(2026, 9, 8)
    _ran_stock, ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=yesterday
    )

    assert ran_macro is True
    assert "macro" in log


async def test_a_failing_macro_check_does_not_block_the_stock_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")
    _calls(monkeypatch, scan_macro, log, "macro", raises=True)

    ran_stock, ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=None
    )

    assert ran_stock is True
    assert ran_macro is True
    assert log == ["crypto", "stock_scan", "reconfirm", "macro"]
