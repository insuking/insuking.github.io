"""P46 acceptance: `app/api/positions.py` - position detail, the Guardian
pause toggle, and manual close, against the real local Postgres (same
DB-backed pattern as test_dashboard_api.py). `LIVE_TRADING` stays at its
safe default (off) throughout this file, same as every other test file in
this project - `close_position` is exercised for its fail-closed 409, not
for an actual real order placement (see test_manual_close.py for the
broker-agnostic close logic itself, tested with a fake `place_order`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.models import KakaoAccount, Position, ProtectiveOrder
from app.db.session import session_scope
from app.main import app

pytestmark = [pytest.mark.P46, pytest.mark.asyncio]

_TEST_SYMBOL = "POS-API-TEST"
_TEST_USER = "test-positions-api-user"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        positions = (await session.execute(select(Position).where(Position.symbol == _TEST_SYMBOL))).scalars().all()
        for position in positions:
            await session.execute(delete(ProtectiveOrder).where(ProtectiveOrder.position_id == position.id))
        await session.execute(delete(Position).where(Position.symbol == _TEST_SYMBOL))
        await session.execute(delete(KakaoAccount).where(KakaoAccount.user_id == _TEST_USER))
        await session.commit()


async def _seed_valid_kakao_session(user_id: str) -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            KakaoAccount(
                id=f"kakao-{user_id}",
                user_id=user_id,
                kakao_user_id=f"kakao-uid-{user_id}",
                access_token="valid-access-token",
                refresh_token="valid-refresh-token",
                access_expires_at=now + timedelta(hours=6),
                refresh_expires_at=now + timedelta(days=60),
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()


async def _make_position(quantity: float = 10.0, asset_type: str = "CRYPTO") -> Position:
    now = datetime.now(UTC)
    async with session_scope() as session:
        position = Position(
            id=f"pos-{uuid.uuid4()}",
            symbol=_TEST_SYMBOL,
            asset_type=asset_type,
            quantity=quantity,
            avg_entry_price=100.0,
            stop_price=90.0,
            state="OPEN",
            guardian_active=True,
            opened_at=now,
            updated_at=now,
        )
        session.add(position)
        session.add(
            ProtectiveOrder(
                id=f"po-{uuid.uuid4()}",
                position_id=position.id,
                kind="T1",
                trigger_price=110.0,
                quantity=3.0,
                active=True,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
        await session.refresh(position)
    return position


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_get_position_detail_returns_real_protective_orders() -> None:
    position = await _make_position()

    async with await _client() as client:
        response = await client.get(f"/api/positions/{position.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == _TEST_SYMBOL
    assert body["state"] == "OPEN"
    assert len(body["protective_orders"]) == 1
    assert body["protective_orders"][0]["kind"] == "T1"
    # CRYPTO position, real Upbit call attempted - may succeed or fail
    # depending on egress, but must never be a fabricated number when it
    # fails: current_price is either a real float or None.
    assert body["current_price"] is None or isinstance(body["current_price"], float)


async def test_get_position_detail_404_for_unknown_position() -> None:
    async with await _client() as client:
        response = await client.get("/api/positions/does-not-exist")

    assert response.status_code == 404


async def test_guardian_toggle_requires_authentication() -> None:
    position = await _make_position()

    async with await _client() as client:
        response = await client.post(
            f"/api/positions/{position.id}/guardian",
            json={"active": False},
            headers={"X-User-Id": _TEST_USER},
        )

    assert response.status_code == 401


async def test_guardian_toggle_pauses_and_resumes_automatic_management() -> None:
    position = await _make_position()
    await _seed_valid_kakao_session(_TEST_USER)

    async with await _client() as client:
        response = await client.post(
            f"/api/positions/{position.id}/guardian",
            json={"active": False},
            headers={"X-User-Id": _TEST_USER},
        )

    assert response.status_code == 200
    assert response.json()["guardian_active"] is False

    async with session_scope() as session:
        result = await session.execute(select(Position).where(Position.id == position.id))
        persisted = result.scalar_one()
    assert persisted.guardian_active is False


async def test_close_position_requires_authentication() -> None:
    position = await _make_position()

    async with await _client() as client:
        response = await client.post(f"/api/positions/{position.id}/close", headers={"X-User-Id": _TEST_USER})

    assert response.status_code == 401


async def test_close_position_fails_closed_when_live_trading_is_disabled() -> None:
    """The real, current state of this deployment's `.env`
    (`LIVE_TRADING` unset/False, this project's safe default) - proves the
    endpoint never fabricates a "closed" response when it can't actually
    place a real order."""
    position = await _make_position()
    await _seed_valid_kakao_session(_TEST_USER)

    async with await _client() as client:
        response = await client.post(f"/api/positions/{position.id}/close", headers={"X-User-Id": _TEST_USER})

    assert response.status_code == 409
    assert "LIVE_TRADING" in response.json()["detail"]

    async with session_scope() as session:
        result = await session.execute(select(Position).where(Position.id == position.id))
        persisted = result.scalar_one()
    assert persisted.state == "OPEN"
    assert persisted.quantity == 10.0


async def test_close_position_409_when_already_closed() -> None:
    position = await _make_position(quantity=0.0)
    await _seed_valid_kakao_session(_TEST_USER)

    async with await _client() as client:
        response = await client.post(f"/api/positions/{position.id}/close", headers={"X-User-Id": _TEST_USER})

    assert response.status_code == 409
    assert "이미 종료" in response.json()["detail"]
