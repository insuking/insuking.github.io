"""P45: app/account/balance.py - real combined KIS+Upbit balance
aggregation. Class methods are monkeypatched directly (same pattern as
test_dashboard_api.py's P42 live-prices tests) rather than mocking httpx
transport, since fetch_kis_total_value()/fetch_upbit_total_value() build
their own short-lived httpx.AsyncClient internally."""

from __future__ import annotations

import pytest

from app.account.balance import (
    CombinedBalance,
    fetch_combined_balance,
    fetch_kis_total_value,
    fetch_upbit_total_value,
)
from app.core.config import Settings, get_settings
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.rest_client import AccountBalance, KisRestClient
from app.integrations.upbit.errors import UpbitApiError
from app.integrations.upbit.orders import UpbitOrderClient
from app.integrations.upbit.rest_client import UpbitRestClient

pytestmark = [pytest.mark.P45, pytest.mark.asyncio]


def _configured_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        kis_app_key="test-key",
        kis_app_secret="test-secret",
        kis_account_no="12345678-01",
        upbit_access_key="test-access",
        upbit_secret_key="test-secret",
    )


async def test_fetch_kis_total_value_returns_none_when_not_configured() -> None:
    result = await fetch_kis_total_value(Settings())  # type: ignore[call-arg]
    assert result is None


async def test_fetch_kis_total_value_returns_real_total(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_account_balance(self: KisRestClient, cano: str, acnt_prdt_cd: str, paper_trading: bool = True):
        assert cano == "12345678"
        assert acnt_prdt_cd == "01"
        return AccountBalance(cash=100.0, securities_value=200.0, total_value=300.0)

    monkeypatch.setattr(KisRestClient, "get_account_balance", _fake_get_account_balance)

    result = await fetch_kis_total_value(_configured_settings())

    assert result == 300.0


async def test_fetch_kis_total_value_degrades_to_none_on_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(self: KisRestClient, cano: str, acnt_prdt_cd: str, paper_trading: bool = True):
        raise KisApiError("boom")

    monkeypatch.setattr(KisRestClient, "get_account_balance", _boom)

    result = await fetch_kis_total_value(_configured_settings())

    assert result is None


async def test_fetch_upbit_total_value_returns_none_when_not_configured() -> None:
    result = await fetch_upbit_total_value(Settings())  # type: ignore[call-arg]
    assert result is None


async def test_fetch_upbit_total_value_sums_krw_cash_and_coin_value(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_accounts(self: UpbitOrderClient):
        return [
            {"currency": "KRW", "balance": "1000000.0", "locked": "0.0"},
            {"currency": "BTC", "balance": "0.01", "locked": "0.0"},
            {"currency": "ETH", "balance": "0.0", "locked": "0.0"},  # zero balance - skipped
        ]

    async def _fake_get_ticker_price(self: UpbitRestClient, market: str) -> float:
        assert market == "KRW-BTC"
        return 90_000_000.0

    monkeypatch.setattr(UpbitOrderClient, "get_accounts", _fake_get_accounts)
    monkeypatch.setattr(UpbitRestClient, "get_ticker_price", _fake_get_ticker_price)

    result = await fetch_upbit_total_value(_configured_settings())

    assert result == pytest.approx(1_000_000.0 + 0.01 * 90_000_000.0)


async def test_fetch_upbit_total_value_skips_a_currency_whose_ticker_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_get_accounts(self: UpbitOrderClient):
        return [
            {"currency": "KRW", "balance": "500000.0", "locked": "0.0"},
            {"currency": "DELISTED", "balance": "10.0", "locked": "0.0"},
        ]

    async def _boom(self: UpbitRestClient, market: str) -> float:
        raise UpbitApiError(404, "not_found", "no such market")

    monkeypatch.setattr(UpbitOrderClient, "get_accounts", _fake_get_accounts)
    monkeypatch.setattr(UpbitRestClient, "get_ticker_price", _boom)

    result = await fetch_upbit_total_value(_configured_settings())

    assert result == 500000.0  # only KRW cash counted, the failed currency's value skipped


async def test_fetch_upbit_total_value_degrades_to_none_when_accounts_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(self: UpbitOrderClient):
        raise UpbitApiError(401, "unauthorized", "bad key")

    monkeypatch.setattr(UpbitOrderClient, "get_accounts", _boom)

    result = await fetch_upbit_total_value(_configured_settings())

    assert result is None


async def test_fetch_combined_balance_combines_both_brokers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_kis(self: KisRestClient, cano: str, acnt_prdt_cd: str, paper_trading: bool = True):
        return AccountBalance(cash=0.0, securities_value=0.0, total_value=1_000_000.0)

    async def _fake_accounts(self: UpbitOrderClient):
        return [{"currency": "KRW", "balance": "500000.0", "locked": "0.0"}]

    monkeypatch.setattr(KisRestClient, "get_account_balance", _fake_kis)
    monkeypatch.setattr(UpbitOrderClient, "get_accounts", _fake_accounts)

    combined = await fetch_combined_balance(_configured_settings())

    assert combined == CombinedBalance(kis_total_value=1_000_000.0, upbit_total_value=500000.0)
    assert combined.total_assets == 1_500_000.0


async def test_combined_balance_total_assets_treats_none_as_zero() -> None:
    combined = CombinedBalance(kis_total_value=None, upbit_total_value=500.0)
    assert combined.total_assets == 500.0

    both_none = CombinedBalance(kis_total_value=None, upbit_total_value=None)
    assert both_none.total_assets == 0.0
