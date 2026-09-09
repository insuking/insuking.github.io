from datetime import UTC, datetime

import pytest

from scripts import reconfirm_entries, scan_crypto, scan_stocks
from scripts.scheduler import run_cycle

pytestmark = pytest.mark.P32

# A real Wednesday, mid-session KST (12:00 KST == 03:00 UTC).
_TRADING_HOURS_NOW = datetime(2026, 9, 9, 3, 0, tzinfo=UTC)
# Same Wednesday, well outside the 09:00-15:30 KST session.
_AFTER_HOURS_NOW = datetime(2026, 9, 9, 14, 0, tzinfo=UTC)  # 23:00 KST


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

    await run_cycle(_AFTER_HOURS_NOW, seconds_since_last_stock_run=None)

    assert log == ["crypto"]


async def test_stock_pass_runs_when_in_trading_hours_and_never_run_before(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")

    ran_stock = await run_cycle(_TRADING_HOURS_NOW, seconds_since_last_stock_run=None)

    assert ran_stock is True
    assert log == ["crypto", "stock_scan", "reconfirm"]


async def test_stock_pass_skipped_outside_trading_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")

    ran_stock = await run_cycle(_AFTER_HOURS_NOW, seconds_since_last_stock_run=None)

    assert ran_stock is False
    assert log == ["crypto"]


async def test_stock_pass_skipped_when_run_too_recently(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")

    ran_stock = await run_cycle(_TRADING_HOURS_NOW, seconds_since_last_stock_run=60.0)

    assert ran_stock is False
    assert log == ["crypto"]


async def test_stock_pass_runs_again_once_the_interval_has_elapsed(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")

    ran_stock = await run_cycle(_TRADING_HOURS_NOW, seconds_since_last_stock_run=1_800.0)

    assert ran_stock is True
    assert log == ["crypto", "stock_scan", "reconfirm"]


async def test_a_failing_crypto_scan_does_not_block_the_stock_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto", raises=True)
    _calls(monkeypatch, scan_stocks, log, "stock_scan")
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")

    ran_stock = await run_cycle(_TRADING_HOURS_NOW, seconds_since_last_stock_run=None)

    assert ran_stock is True
    assert log == ["crypto", "stock_scan", "reconfirm"]


async def test_a_failing_stock_scan_does_not_prevent_reconfirm_from_still_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log: list[str] = []
    _calls(monkeypatch, scan_crypto, log, "crypto")
    _calls(monkeypatch, scan_stocks, log, "stock_scan", raises=True)
    _calls(monkeypatch, reconfirm_entries, log, "reconfirm")

    ran_stock = await run_cycle(_TRADING_HOURS_NOW, seconds_since_last_stock_run=None)

    assert ran_stock is True
    assert log == ["crypto", "stock_scan", "reconfirm"]
