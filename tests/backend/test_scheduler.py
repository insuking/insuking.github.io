from datetime import UTC, date, datetime

import pytest

from scripts import reconfirm_entries, scan_crypto, scan_macro, scan_stocks, snapshot_balance
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


def _patch_all(monkeypatch: pytest.MonkeyPatch, log: list[str], **overrides: bool) -> None:
    """Fakes every scheduled job (P45's balance snapshot included) so no
    test makes a real network/DB call - `overrides` sets `raises=True` for
    specific labels, e.g. `_patch_all(monkeypatch, log, crypto=True)`."""
    _calls(monkeypatch, scan_crypto, log, "crypto", raises=overrides.get("crypto", False))
    _calls(monkeypatch, snapshot_balance, log, "balance", raises=overrides.get("balance", False))
    _calls(monkeypatch, scan_stocks, log, "stock_scan", raises=overrides.get("stock_scan", False))
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm", raises=overrides.get("reconfirm", False))
    _calls(monkeypatch, scan_macro, log, "macro", raises=overrides.get("macro", False))


async def test_crypto_scan_always_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log)

    await run_cycle(_AFTER_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE)

    assert log == ["crypto", "balance"]


async def test_balance_snapshot_always_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log)

    await run_cycle(_AFTER_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE)

    assert "balance" in log


async def test_stock_pass_runs_when_in_trading_hours_and_never_run_before(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log)

    ran_stock, _ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_stock is True
    assert log == ["crypto", "balance", "stock_scan", "reconfirm"]


async def test_stock_pass_skipped_outside_trading_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log)

    ran_stock, _ran_macro = await run_cycle(
        _AFTER_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_stock is False
    assert log == ["crypto", "balance"]


async def test_stock_pass_skipped_when_run_too_recently(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log)

    ran_stock, _ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=60.0, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_stock is False
    assert log == ["crypto", "balance"]


async def test_stock_pass_runs_again_once_the_interval_has_elapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log)

    ran_stock, _ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=1_800.0, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_stock is True
    assert log == ["crypto", "balance", "stock_scan", "reconfirm"]


async def test_a_failing_crypto_scan_does_not_block_the_stock_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log, crypto=True)

    ran_stock, _ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_stock is True
    assert log == ["crypto", "balance", "stock_scan", "reconfirm"]


async def test_a_failing_balance_snapshot_does_not_block_the_stock_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log, balance=True)

    ran_stock, _ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_stock is True
    assert log == ["crypto", "balance", "stock_scan", "reconfirm"]


async def test_a_failing_stock_scan_does_not_prevent_reconfirm_from_still_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log, stock_scan=True)

    ran_stock, _ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_stock is True
    assert log == ["crypto", "balance", "stock_scan", "reconfirm"]


async def test_macro_pass_runs_at_or_after_0820_kst_when_not_yet_run_today(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log)

    _ran_stock, ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=None
    )

    assert ran_macro is True
    assert "macro" in log


async def test_macro_pass_skipped_before_0820_kst(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log)

    _ran_stock, ran_macro = await run_cycle(
        _BEFORE_MACRO_TIME_NOW, seconds_since_last_stock_run=None, last_macro_run_date=None
    )

    assert ran_macro is False
    assert "macro" not in log


async def test_macro_pass_skipped_when_already_run_today(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log)

    _ran_stock, ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=_SAME_KST_DATE
    )

    assert ran_macro is False
    assert "macro" not in log


async def test_macro_pass_runs_again_the_next_kst_calendar_date(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log)

    yesterday = date(2026, 9, 8)
    _ran_stock, ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=yesterday
    )

    assert ran_macro is True
    assert "macro" in log


async def test_a_failing_macro_check_does_not_block_the_stock_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _patch_all(monkeypatch, log, macro=True)

    ran_stock, ran_macro = await run_cycle(
        _TRADING_HOURS_NOW, seconds_since_last_stock_run=None, last_macro_run_date=None
    )

    assert ran_stock is True
    assert ran_macro is True
    assert log == ["crypto", "balance", "stock_scan", "reconfirm", "macro"]
