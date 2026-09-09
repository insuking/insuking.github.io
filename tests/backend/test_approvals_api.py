"""P13 acceptance: the approval HTTP API, end-to-end against the real app
and real local Postgres via httpx.ASGITransport (no mocking of our own
code) - only the "is this user's Kakao session valid" check is made cheap
to test by inserting a KakaoAccount row with a far-future access token
expiry, so `KakaoTokenStore.get_valid_access_token` returns it without ever
making a network call (see app/integrations/kakao/token_store.py - a
still-valid token is returned directly, no refresh() call happens).

The STOCK-dispatch tests near the bottom (P29) monkeypatch
`gather_kis_revalidation_input`/`KisExecutionProvider.place_order` - the two
places `_execute_stock_recommendation()` would otherwise hit a real KIS
connection - so they exercise the real endpoint wiring
(app/api/approvals.py's new STOCK-vs-CRYPTO dispatch) without ever needing
real KIS credentials or network access.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

import app.api.approvals as approvals_api
from app.approval.pin import hash_pin
from app.approval.revalidation import RevalidationInput
from app.approval.service import ApprovalService
from app.core.config import get_settings
from app.db.models import Approval, ApprovalEvent, KakaoAccount, Order, TradePlan
from app.db.models import Recommendation as RecommendationRow
from app.db.session import session_scope
from app.integrations.kis.execution import KisExecutionProvider
from app.main import app

pytestmark = [pytest.mark.P13, pytest.mark.asyncio]

_TEST_USER_ID = "test-user-approvals-api"
_TEST_PIN = "9999"


@pytest_asyncio.fixture(autouse=True)
async def _configure_pin():  # type: ignore[no-untyped-def]
    settings = get_settings()
    original = settings.app_pin_hash
    settings.app_pin_hash = hash_pin(_TEST_PIN)
    yield
    settings.app_pin_hash = original


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    """`@pytest_asyncio.fixture` (not plain `@pytest.fixture`, which this
    file used to use) - matching `tests/backend/conftest.py`'s own
    `_reset_connection_singletons` pattern: in this project's pinned
    pytest-asyncio version, `asyncio_mode = auto` does not reliably drive a
    plain `@pytest.fixture` async generator's teardown, so this autouse
    cleanup was silently never running its post-`yield` deletes, leaking
    rows across test runs (confirmed - it left a stale `kakao_accounts` row
    that broke later runs with a primary-key collision)."""
    yield
    async with session_scope() as session:
        approvals = (
            await session.execute(select(Approval).where(Approval.user_id == _TEST_USER_ID))
        ).scalars().all()
        for approval in approvals:
            trade_plan_ids = (
                (await session.execute(select(TradePlan.id).where(TradePlan.approval_id == approval.id)))
                .scalars()
                .all()
            )
            if trade_plan_ids:
                # Orders FK-reference trade_plans - must go first, or the
                # TradePlan delete below violates orders_trade_plan_id_fkey.
                await session.execute(delete(Order).where(Order.trade_plan_id.in_(trade_plan_ids)))
            await session.execute(delete(TradePlan).where(TradePlan.approval_id == approval.id))
            await session.execute(delete(ApprovalEvent).where(ApprovalEvent.approval_id == approval.id))
        await session.execute(delete(Approval).where(Approval.user_id == _TEST_USER_ID))
        await session.execute(delete(RecommendationRow).where(RecommendationRow.symbol == "KRW-XRP-API-TEST"))
        await session.execute(delete(RecommendationRow).where(RecommendationRow.symbol == _TEST_STOCK_SYMBOL))
        await session.execute(delete(Order).where(Order.symbol == _TEST_STOCK_SYMBOL))
        await session.execute(
            delete(KakaoAccount).where(KakaoAccount.user_id.in_([_TEST_USER_ID, "someone-else"]))
        )
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


async def _create_approval() -> tuple[str, str]:
    """Returns (recommendation_id, plaintext_token)."""
    now = datetime.now(UTC)
    async with session_scope() as session:
        rec = RecommendationRow(
            id=f"rec-api-{now.timestamp()}",
            symbol="KRW-XRP-API-TEST",
            asset_type="CRYPTO",
            score=88.0,
            state="CONFIRMED_BREAKOUT",
            entry_low=4000.0,
            entry_high=4020.0,
            stop_price=3900.0,
            t1_price=4100.0,
            t1_percent=30.0,
            t2_price=4200.0,
            t2_percent=30.0,
            runner_percent=40.0,
            expected_max_loss=5000.0,
            risk_reward=2.0,
            reasons='["Confirmed breakout"]',
            risks='["Standard breakout risk"]',
            created_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        session.add(rec)
        await session.commit()

        service = ApprovalService(session)
        _, plaintext = await service.create_approval(rec.id, _TEST_USER_ID)
        return rec.id, plaintext


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_get_approval_requires_authentication() -> None:
    _, token = await _create_approval()
    async with await _client() as client:
        response = await client.get(f"/api/approvals/{token}", headers={"X-User-Id": _TEST_USER_ID})
    assert response.status_code == 401


async def test_get_approval_returns_detail_for_authenticated_user() -> None:
    await _seed_valid_kakao_session(_TEST_USER_ID)
    _, token = await _create_approval()

    async with await _client() as client:
        response = await client.get(f"/api/approvals/{token}", headers={"X-User-Id": _TEST_USER_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "KRW-XRP-API-TEST"
    assert body["approval_state"] == "OPENED"
    assert body["confidence"] == "HIGH"
    assert body["reasons"] == ["Confirmed breakout"]
    assert body["remaining_seconds"] > 0


async def test_get_approval_404_for_unknown_token() -> None:
    await _seed_valid_kakao_session(_TEST_USER_ID)
    async with await _client() as client:
        response = await client.get(
            "/api/approvals/does-not-exist", headers={"X-User-Id": _TEST_USER_ID}
        )
    assert response.status_code == 404


async def test_get_approval_403_for_wrong_user() -> None:
    await _seed_valid_kakao_session(_TEST_USER_ID)
    await _seed_valid_kakao_session("someone-else")
    _, token = await _create_approval()

    async with await _client() as client:
        response = await client.get(f"/api/approvals/{token}", headers={"X-User-Id": "someone-else"})

    assert response.status_code == 403


async def test_decide_reject_then_reuse_returns_410() -> None:
    await _seed_valid_kakao_session(_TEST_USER_ID)
    _, token = await _create_approval()

    async with await _client() as client:
        first = await client.post(
            f"/api/approvals/{token}/decide",
            json={"decision": "REJECT"},
            headers={"X-User-Id": _TEST_USER_ID},
        )
        assert first.status_code == 200
        assert first.json()["approval_state"] == "REJECTED"

        second = await client.post(
            f"/api/approvals/{token}/decide",
            json={"decision": "REJECT"},
            headers={"X-User-Id": _TEST_USER_ID},
        )
    assert second.status_code == 410


async def test_decide_approve_requires_pin_and_succeeds_with_it() -> None:
    await _seed_valid_kakao_session(_TEST_USER_ID)
    _, token = await _create_approval()

    async with await _client() as client:
        wrong_pin = await client.post(
            f"/api/approvals/{token}/decide",
            json={"decision": "APPROVE", "pin": "0000"},
            headers={"X-User-Id": _TEST_USER_ID},
        )
        assert wrong_pin.status_code == 400

        correct_pin = await client.post(
            f"/api/approvals/{token}/decide",
            json={"decision": "APPROVE", "pin": _TEST_PIN},
            headers={"X-User-Id": _TEST_USER_ID},
        )
    assert correct_pin.status_code == 200
    assert correct_pin.json()["approval_state"] == "APPROVED"


async def test_decide_approve_with_amount_change_without_amount_is_400() -> None:
    await _seed_valid_kakao_session(_TEST_USER_ID)
    _, token = await _create_approval()

    async with await _client() as client:
        response = await client.post(
            f"/api/approvals/{token}/decide",
            json={"decision": "APPROVE_WITH_AMOUNT_CHANGE", "pin": _TEST_PIN},
            headers={"X-User-Id": _TEST_USER_ID},
        )
    assert response.status_code == 400


async def test_decide_hold_returns_200_and_stays_pending() -> None:
    await _seed_valid_kakao_session(_TEST_USER_ID)
    _, token = await _create_approval()

    async with await _client() as client:
        response = await client.post(
            f"/api/approvals/{token}/decide",
            json={"decision": "HOLD"},
            headers={"X-User-Id": _TEST_USER_ID},
        )
    assert response.status_code == 200
    assert response.json()["approval_state"] in ("CREATED", "OPENED")


# --- P29: STOCK recommendations dispatch through the execution bridge ------

_TEST_STOCK_SYMBOL = "STOCKAPI-TEST"


async def _create_stock_approval() -> tuple[str, str]:
    """Same shape as `_create_approval()` but `asset_type="STOCK"` - the
    only thing that makes `decide_approval()` call
    `_execute_stock_recommendation()` after APPROVE. Returns
    (recommendation_id, plaintext_token)."""
    now = datetime.now(UTC)
    async with session_scope() as session:
        rec = RecommendationRow(
            id=f"rec-stock-api-{now.timestamp()}",
            symbol=_TEST_STOCK_SYMBOL,
            asset_type="STOCK",
            score=88.0,
            state="CONFIRMED_BREAKOUT",
            entry_low=1000.0,
            entry_high=1020.0,
            stop_price=900.0,
            t1_price=1100.0,
            t1_percent=30.0,
            t2_price=1200.0,
            t2_percent=30.0,
            runner_percent=40.0,
            expected_max_loss=1000.0,
            risk_reward=2.0,
            reasons='["Confirmed breakout"]',
            risks='["Standard breakout risk"]',
            created_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        session.add(rec)
        await session.commit()

        service = ApprovalService(session)
        _, plaintext = await service.create_approval(rec.id, _TEST_USER_ID)
        return rec.id, plaintext


def _fake_gather(healthy: bool) -> object:
    async def gather(session, rest, approval, recommendation):  # type: ignore[no-untyped-def]
        return RevalidationInput(
            now=datetime.now(UTC),
            approval_expires_at=approval.expires_at,
            recommendation=recommendation,
            current_price=recommendation.entry_low,
            market_data_healthy=healthy,
            broker_healthy=healthy,
        )

    return gather


async def _fake_place_order(self, session, *, trade_plan_id, symbol, side, **extra):  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    order = Order(
        id=f"fake-order-{now.timestamp()}",
        trade_plan_id=trade_plan_id,
        symbol=symbol,
        side=side,
        order_type="LIMIT",
        quantity=float(extra["quantity"]),
        price=float(extra["price"]),
        status="SUBMITTED",
        broker="KIS",
        broker_order_id="FAKE-ODNO",
        created_at=now,
        updated_at=now,
    )
    session.add(order)
    await session.commit()
    return order


async def test_decide_approve_stock_executes_and_returns_executed_outcome(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(approvals_api, "gather_kis_revalidation_input", _fake_gather(healthy=True))
    monkeypatch.setattr(KisExecutionProvider, "place_order", _fake_place_order)

    await _seed_valid_kakao_session(_TEST_USER_ID)
    _, token = await _create_stock_approval()

    async with await _client() as client:
        response = await client.post(
            f"/api/approvals/{token}/decide",
            json={"decision": "APPROVE", "pin": _TEST_PIN},
            headers={"X-User-Id": _TEST_USER_ID},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["approval_state"] == "EXECUTED"
    assert body["execution_outcome"] == "EXECUTED"
    assert body["execution_reasons"] == []


async def test_decide_approve_stock_invalidated_on_unhealthy_market_data(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(approvals_api, "gather_kis_revalidation_input", _fake_gather(healthy=False))
    monkeypatch.setattr(KisExecutionProvider, "place_order", _fake_place_order)

    await _seed_valid_kakao_session(_TEST_USER_ID)
    _, token = await _create_stock_approval()

    async with await _client() as client:
        response = await client.post(
            f"/api/approvals/{token}/decide",
            json={"decision": "APPROVE", "pin": _TEST_PIN},
            headers={"X-User-Id": _TEST_USER_ID},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["approval_state"] == "INVALIDATED"
    assert body["execution_outcome"] == "INVALIDATED"
    assert body["execution_reasons"]


async def test_decide_reject_stock_never_touches_execution_bridge(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """REJECT must never reach `_execute_stock_recommendation()` -
    monkeypatching `gather_kis_revalidation_input` to raise proves it's
    never called on this path."""

    async def _boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("gather_kis_revalidation_input must not be called for a REJECT decision")

    monkeypatch.setattr(approvals_api, "gather_kis_revalidation_input", _boom)

    await _seed_valid_kakao_session(_TEST_USER_ID)
    _, token = await _create_stock_approval()

    async with await _client() as client:
        response = await client.post(
            f"/api/approvals/{token}/decide",
            json={"decision": "REJECT"},
            headers={"X-User-Id": _TEST_USER_ID},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["approval_state"] == "REJECTED"
    assert body["execution_outcome"] is None
