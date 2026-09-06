"""P13 acceptance: the approval state machine, against the real local
Postgres (like test_kakao_token_store.py) - what's being proven is that
state transitions and the audit trail actually persist correctly, not that
some HTTP call was well-formed.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.approval.errors import (
    ApprovalGoneError,
    ApprovalNotFoundError,
    ApprovalUserMismatchError,
    InvalidDecisionError,
)
from app.approval.pin import hash_pin
from app.approval.service import ApprovalDecision, ApprovalService
from app.core.config import Settings
from app.db.models import Approval, ApprovalEvent
from app.db.models import Recommendation as RecommendationRow
from app.db.session import session_scope

pytestmark = [pytest.mark.P13, pytest.mark.asyncio]

_TEST_USER_ID = "test-user-approval-service"


def _settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {"app_pin_hash": hash_pin("1234")}
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


async def _create_recommendation(session, **overrides: object) -> RecommendationRow:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    defaults: dict[str, object] = {
        "id": f"rec-{now.timestamp()}",
        "symbol": "KRW-XRP",
        "asset_type": "CRYPTO",
        "score": 80.0,
        "state": "CONFIRMED_BREAKOUT",
        "entry_low": 4000.0,
        "entry_high": 4020.0,
        "stop_price": 3900.0,
        "t1_price": 4100.0,
        "t1_percent": 30.0,
        "t2_price": 4200.0,
        "t2_percent": 30.0,
        "runner_percent": 40.0,
        "expected_max_loss": 5000.0,
        "risk_reward": 2.0,
        "reasons": "[]",
        "risks": "[]",
        "created_at": now,
        "expires_at": now + timedelta(minutes=5),
    }
    defaults.update(overrides)
    rec = RecommendationRow(**defaults)
    session.add(rec)
    await session.commit()
    return rec


@pytest.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        result = await session.execute(select(Approval).where(Approval.user_id == _TEST_USER_ID))
        approvals = result.scalars().all()
        for approval in approvals:
            await session.execute(delete(ApprovalEvent).where(ApprovalEvent.approval_id == approval.id))
        await session.execute(delete(Approval).where(Approval.user_id == _TEST_USER_ID))
        await session.execute(delete(RecommendationRow).where(RecommendationRow.symbol == "KRW-XRP-TEST"))
        await session.commit()


async def test_create_approval_starts_in_created_state_with_audit_event() -> None:
    async with session_scope() as session:
        rec = await _create_recommendation(session, symbol="KRW-XRP-TEST")
        service = ApprovalService(session, settings=_settings())
        approval, plaintext = await service.create_approval(rec.id, _TEST_USER_ID)

        assert approval.state == "CREATED"
        assert plaintext
        assert approval.token_hash != plaintext  # never stores the plaintext

        events = (
            await session.execute(select(ApprovalEvent).where(ApprovalEvent.approval_id == approval.id))
        ).scalars().all()
        assert len(events) == 1
        assert events[0].from_state is None
        assert events[0].to_state == "CREATED"


async def test_open_by_token_transitions_created_to_opened() -> None:
    async with session_scope() as session:
        rec = await _create_recommendation(session, symbol="KRW-XRP-TEST")
        service = ApprovalService(session, settings=_settings())
        _, plaintext = await service.create_approval(rec.id, _TEST_USER_ID)

        view = await service.open_by_token(plaintext, _TEST_USER_ID)

        assert view.approval.state == "OPENED"
        assert view.approval.opened_at is not None
        assert view.recommendation.id == rec.id
        assert view.remaining_seconds > 0


async def test_open_by_token_is_idempotent_on_repeat_views() -> None:
    async with session_scope() as session:
        rec = await _create_recommendation(session, symbol="KRW-XRP-TEST")
        service = ApprovalService(session, settings=_settings())
        approval, plaintext = await service.create_approval(rec.id, _TEST_USER_ID)

        await service.open_by_token(plaintext, _TEST_USER_ID)
        await service.open_by_token(plaintext, _TEST_USER_ID)

        events = (
            await session.execute(select(ApprovalEvent).where(ApprovalEvent.approval_id == approval.id))
        ).scalars().all()
        # CREATED, then a single OPENED - the second view must not add another.
        assert [e.to_state for e in events] == ["CREATED", "OPENED"]


async def test_open_by_token_raises_not_found_for_unknown_token() -> None:
    async with session_scope() as session:
        service = ApprovalService(session, settings=_settings())
        with pytest.raises(ApprovalNotFoundError):
            await service.open_by_token("no-such-token", _TEST_USER_ID)


async def test_open_by_token_raises_user_mismatch() -> None:
    async with session_scope() as session:
        rec = await _create_recommendation(session, symbol="KRW-XRP-TEST")
        service = ApprovalService(session, settings=_settings())
        _, plaintext = await service.create_approval(rec.id, _TEST_USER_ID)

        with pytest.raises(ApprovalUserMismatchError):
            await service.open_by_token(plaintext, "someone-else")


async def test_open_by_token_lazily_expires_past_ttl() -> None:
    async with session_scope() as session:
        rec = await _create_recommendation(session, symbol="KRW-XRP-TEST")
        service = ApprovalService(session, settings=_settings())
        _, plaintext = await service.create_approval(rec.id, _TEST_USER_ID, ttl_seconds=-1)

        view = await service.open_by_token(plaintext, _TEST_USER_ID)

        assert view.approval.state == "EXPIRED"
        assert view.remaining_seconds == 0


async def test_decide_reject_transitions_and_consumes_token() -> None:
    async with session_scope() as session:
        rec = await _create_recommendation(session, symbol="KRW-XRP-TEST")
        service = ApprovalService(session, settings=_settings())
        _, plaintext = await service.create_approval(rec.id, _TEST_USER_ID)

        result = await service.decide(plaintext, _TEST_USER_ID, ApprovalDecision.REJECT)
        assert result.state == "REJECTED"
        assert result.decided_at is not None

        with pytest.raises(ApprovalGoneError):
            await service.decide(plaintext, _TEST_USER_ID, ApprovalDecision.REJECT)


async def test_decide_hold_does_not_change_state_or_consume_token() -> None:
    async with session_scope() as session:
        rec = await _create_recommendation(session, symbol="KRW-XRP-TEST")
        service = ApprovalService(session, settings=_settings())
        _, plaintext = await service.create_approval(rec.id, _TEST_USER_ID)

        result = await service.decide(plaintext, _TEST_USER_ID, ApprovalDecision.HOLD)
        assert result.state == "CREATED"

        # token still usable afterward - HOLD never consumes it.
        second = await service.decide(plaintext, _TEST_USER_ID, ApprovalDecision.REJECT)
        assert second.state == "REJECTED"


async def test_decide_approve_requires_correct_pin() -> None:
    async with session_scope() as session:
        rec = await _create_recommendation(session, symbol="KRW-XRP-TEST")
        service = ApprovalService(session, settings=_settings())
        _, plaintext = await service.create_approval(rec.id, _TEST_USER_ID)

        from app.approval.errors import PinIncorrectError

        with pytest.raises(PinIncorrectError):
            await service.decide(plaintext, _TEST_USER_ID, ApprovalDecision.APPROVE, pin="0000")

        result = await service.decide(plaintext, _TEST_USER_ID, ApprovalDecision.APPROVE, pin="1234")
        assert result.state == "APPROVED"


async def test_decide_approve_with_amount_change_requires_positive_amount() -> None:
    async with session_scope() as session:
        rec = await _create_recommendation(session, symbol="KRW-XRP-TEST")
        service = ApprovalService(session, settings=_settings())
        approval, plaintext = await service.create_approval(rec.id, _TEST_USER_ID)

        with pytest.raises(InvalidDecisionError):
            await service.decide(
                plaintext, _TEST_USER_ID, ApprovalDecision.APPROVE_WITH_AMOUNT_CHANGE, pin="1234"
            )

        result = await service.decide(
            plaintext,
            _TEST_USER_ID,
            ApprovalDecision.APPROVE_WITH_AMOUNT_CHANGE,
            override_amount=123456.0,
            pin="1234",
        )
        assert result.state == "APPROVED"

        events = (
            await session.execute(select(ApprovalEvent).where(ApprovalEvent.approval_id == approval.id))
        ).scalars().all()
        approved_event = next(e for e in events if e.to_state == "APPROVED")
        assert approved_event.detail is not None
        assert "123456" in approved_event.detail


async def test_decide_raises_gone_after_expiry() -> None:
    async with session_scope() as session:
        rec = await _create_recommendation(session, symbol="KRW-XRP-TEST")
        service = ApprovalService(session, settings=_settings())
        _, plaintext = await service.create_approval(rec.id, _TEST_USER_ID, ttl_seconds=-1)

        with pytest.raises(ApprovalGoneError):
            await service.decide(plaintext, _TEST_USER_ID, ApprovalDecision.REJECT)


async def test_apply_revalidation_result_invalidates_an_approved_approval() -> None:
    async with session_scope() as session:
        rec = await _create_recommendation(session, symbol="KRW-XRP-TEST")
        service = ApprovalService(session, settings=_settings())
        approval, plaintext = await service.create_approval(rec.id, _TEST_USER_ID)
        await service.decide(plaintext, _TEST_USER_ID, ApprovalDecision.APPROVE, pin="1234")

        await service.apply_revalidation_result(approval, "INVALIDATED", reasons=["price drifted too far"])

        assert approval.state == "INVALIDATED"


async def test_apply_revalidation_result_valid_is_a_noop() -> None:
    async with session_scope() as session:
        rec = await _create_recommendation(session, symbol="KRW-XRP-TEST")
        service = ApprovalService(session, settings=_settings())
        approval, plaintext = await service.create_approval(rec.id, _TEST_USER_ID)
        await service.decide(plaintext, _TEST_USER_ID, ApprovalDecision.APPROVE, pin="1234")

        await service.apply_revalidation_result(approval, "VALID")

        assert approval.state == "APPROVED"
