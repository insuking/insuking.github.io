"""P24: auto-connects the real crypto scan (P23) to paper trading (P20)
against the real local Postgres - open/close decisions and the persisted
exit plan (PaperPosition.stop_price/t2_price) actually round-trip.

Uses `httpx.MockTransport` for Upbit (mocks are for unit tests only - see
docs/UPBIT_NOTES.md) with the same AAA/BBB/CCC breakout fixtures
`test_crypto_scan.py` uses, so `scan_crypto_market()` reliably recommends
KRW-AAA (entry_low=105.5, stop_price=95.0, t2_price=137.0) and never
recommends the flat KRW-BBB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, select

from app.db.models import PaperAccount, PaperFill, PaperOrder, PaperPosition
from app.db.session import session_scope
from app.integrations.upbit.rest_client import UpbitRestClient
from app.scan.auto_paper_trade import run_auto_paper_trading

pytestmark = [pytest.mark.P24, pytest.mark.asyncio]

_ACCOUNT_ID = "test-auto-paper-trade-account"
_START = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)


def _bar(open_: float, high: float, low: float, close: float, volume: float) -> tuple:
    return (open_, high, low, close, volume)


def _opening_range_bars(count: int = 15) -> list[tuple]:
    return [_bar(97.0, 100.0, 95.0, 97.0, 10.0) for _ in range(count)]


def _filler_bars(count: int = 4) -> list[tuple]:
    return [_bar(98.0, 99.0, 96.0, 98.0, 10.0) for _ in range(count)]


def _aaa_candles() -> list[tuple]:
    return [*_opening_range_bars(), *_filler_bars(), _bar(98.0, 106.0, 100.0, 105.5, 200.0)]


def _bbb_candles() -> list[tuple]:
    return [*_opening_range_bars(count=20)]


def _btc_candles() -> list[tuple]:
    return [
        _bar(80_000_000 + i * 40_000, 80_050_000 + i * 40_000, 79_950_000 + i * 40_000, 80_000_000 + i * 40_000, 5.0)
        for i in range(25)
    ]


_CANDLES_BY_MARKET = {"KRW-BTC": _btc_candles(), "KRW-AAA": _aaa_candles(), "KRW-BBB": _bbb_candles()}


def _upbit_candles_json(bars: list[tuple], market: str) -> list[dict]:
    out = []
    for i, (open_, high, low, close, volume) in enumerate(bars):
        candle_time = _START + timedelta(minutes=i)
        out.append(
            {
                "market": market,
                "candle_date_time_utc": candle_time.strftime("%Y-%m-%dT%H:%M:%S"),
                "opening_price": open_,
                "high_price": high,
                "low_price": low,
                "trade_price": close,
                "candle_acc_trade_volume": volume,
            }
        )
    return list(reversed(out))


def _rest_client(ticker_prices: dict[str, float] | None = None) -> UpbitRestClient:
    prices = ticker_prices or {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/market/all":
            return httpx.Response(200, json=[{"market": m, "korean_name": m} for m in _CANDLES_BY_MARKET])
        if path == "/v1/ticker":
            markets = request.url.params["markets"].split(",")
            return httpx.Response(
                200,
                json=[
                    {"market": m, "trade_price": prices.get(m, 100.0), "acc_trade_price_24h": 1_000_000.0}
                    for m in markets
                ],
            )
        if path.startswith("/v1/candles/minutes/"):
            market = request.url.params["market"]
            return httpx.Response(200, json=_upbit_candles_json(_CANDLES_BY_MARKET[market], market))
        raise AssertionError(f"unexpected request path: {path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock.upbit.test")
    return UpbitRestClient(client)


async def _get_position(session, symbol: str) -> PaperPosition | None:  # type: ignore[no-untyped-def]
    result = await session.execute(
        select(PaperPosition).where(PaperPosition.account_id == _ACCOUNT_ID, PaperPosition.symbol == symbol)
    )
    return result.scalar_one_or_none()


@pytest.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        order_ids = (
            (await session.execute(select(PaperOrder.id).where(PaperOrder.account_id == _ACCOUNT_ID)))
            .scalars()
            .all()
        )
        if order_ids:
            await session.execute(delete(PaperFill).where(PaperFill.order_id.in_(order_ids)))
        await session.execute(delete(PaperOrder).where(PaperOrder.account_id == _ACCOUNT_ID))
        await session.execute(delete(PaperPosition).where(PaperPosition.account_id == _ACCOUNT_ID))
        await session.execute(delete(PaperAccount).where(PaperAccount.id == _ACCOUNT_ID))
        await session.commit()


async def test_opens_a_paper_position_for_a_fresh_recommendation_and_stamps_its_exit_plan() -> None:
    async with session_scope() as session:
        report = await run_auto_paper_trading(session, _rest_client(), _ACCOUNT_ID, starting_cash=10_000_000.0)

    assert [o.symbol for o in report.opened] == ["KRW-AAA"]
    assert report.closed == []

    async with session_scope() as session:
        position = await _get_position(session, "KRW-AAA")

    assert position is not None
    assert position.quantity > 0
    assert position.stop_price == pytest.approx(95.0)
    assert position.t2_price == pytest.approx(137.0)


async def test_skips_a_symbol_that_is_already_held() -> None:
    async with session_scope() as session:
        await run_auto_paper_trading(session, _rest_client(), _ACCOUNT_ID, starting_cash=10_000_000.0)

    async with session_scope() as session:
        report = await run_auto_paper_trading(
            session, _rest_client(ticker_prices={"KRW-AAA": 110.0}), _ACCOUNT_ID, starting_cash=10_000_000.0
        )

    assert report.opened == []
    assert any(s.symbol == "KRW-AAA" and "already holding" in s.reason for s in report.skipped)


async def test_closes_a_position_whose_price_has_fallen_through_its_stop() -> None:
    async with session_scope() as session:
        await run_auto_paper_trading(session, _rest_client(), _ACCOUNT_ID, starting_cash=10_000_000.0)

    async with session_scope() as session:
        report = await run_auto_paper_trading(
            session, _rest_client(ticker_prices={"KRW-AAA": 90.0}), _ACCOUNT_ID, starting_cash=10_000_000.0
        )

    assert [c.symbol for c in report.closed] == ["KRW-AAA"]
    assert report.closed[0].exit_reason == "STOP"

    async with session_scope() as session:
        position = await _get_position(session, "KRW-AAA")
    assert position is not None
    assert position.quantity == pytest.approx(0.0)


async def test_closes_a_position_whose_price_has_reached_its_target() -> None:
    async with session_scope() as session:
        await run_auto_paper_trading(session, _rest_client(), _ACCOUNT_ID, starting_cash=10_000_000.0)

    async with session_scope() as session:
        report = await run_auto_paper_trading(
            session, _rest_client(ticker_prices={"KRW-AAA": 140.0}), _ACCOUNT_ID, starting_cash=10_000_000.0
        )

    assert [c.symbol for c in report.closed] == ["KRW-AAA"]
    assert report.closed[0].exit_reason == "TARGET"


async def test_leaves_a_position_open_while_price_is_between_stop_and_target() -> None:
    async with session_scope() as session:
        await run_auto_paper_trading(session, _rest_client(), _ACCOUNT_ID, starting_cash=10_000_000.0)

    async with session_scope() as session:
        report = await run_auto_paper_trading(
            session, _rest_client(ticker_prices={"KRW-AAA": 110.0}), _ACCOUNT_ID, starting_cash=10_000_000.0
        )

    assert report.closed == []

    async with session_scope() as session:
        position = await _get_position(session, "KRW-AAA")
    assert position is not None
    assert position.quantity > 0
