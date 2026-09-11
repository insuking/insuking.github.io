"""P21 acceptance: rate_limit.py's fixed-window counter against real local
Redis, plus an end-to-end check that the decide endpoint actually returns
429 once a token's PIN-attempt budget is exhausted.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.approval.pin import hash_pin
from app.approval.rate_limit import check_and_record_attempt
from app.approval.service import ApprovalService
from app.core.config import get_settings
from app.db.models import Approval, ApprovalEvent, KakaoAccount
from app.db.models import Recommendation as RecommendationRow
from app.db.redis_client import get_redis
from app.db.session import session_scope
from app.main import app

pytestmark = [pytest.mark.P21, pytest.mark.asyncio]

_TEST_USER_ID = "test-user-rate-limit"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():  # type: ignore[no-untyped-def]
    yield
    async with session_scope() as session:
        # The approval's own "CREATED" event is recorded with actor="system"
        # (see ApprovalService.create_approval), not the user id - deleting
        # by approval_id (like test_approvals_api.py's _cleanup) catches
        # every event, not just the ones this user's decisions produced.
        approval_ids = (
            (await session.execute(select(Approval.id).where(Approval.user_id == _TEST_USER_ID)))
            .scalars()
            .all()
        )
        if approval_ids:
            await session.execute(delete(ApprovalEvent).where(ApprovalEvent.approval_id.in_(approval_ids)))
        await session.execute(delete(Approval).where(Approval.user_id == _TEST_USER_ID))
        await session.execute(delete(KakaoAccount).where(KakaoAccount.user_id == _TEST_USER_ID))
        await session.execute(delete(RecommendationRow).where(RecommendationRow.symbol == "RATE-LIMIT-TEST"))
        await session.commit()


async def test_check_and_record_attempt_allows_up_to_max() -> None:
    redis = get_redis()
    key = "rate-limit-pure-1"
    await redis.delete(f"approval_decide_rate_limit:{key}")
    try:
        results = [
            await check_and_record_attempt(redis, key, max_attempts=3, window_seconds=60) for _ in range(3)
        ]
        assert results == [True, True, True]
        blocked = await check_and_record_attempt(redis, key, max_attempts=3, window_seconds=60)
        assert blocked is False
    finally:
        await redis.delete(f"approval_decide_rate_limit:{key}")


async def test_check_and_record_attempt_scoped_per_token() -> None:
    redis = get_redis()
    key_a, key_b = "rate-limit-pure-a", "rate-limit-pure-b"
    for key in (key_a, key_b):
        await redis.delete(f"approval_decide_rate_limit:{key}")
    try:
        for _ in range(3):
            assert await check_and_record_attempt(redis, key_a, max_attempts=3, window_seconds=60) is True
        assert await check_and_record_attempt(redis, key_a, max_attempts=3, window_seconds=60) is False
        # A different token's budget is untouched by key_a's exhaustion.
        assert await check_and_record_attempt(redis, key_b, max_attempts=3, window_seconds=60) is True
    finally:
        for key in (key_a, key_b):
            await redis.delete(f"approval_decide_rate_limit:{key}")


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


async def _create_approval() -> str:
    now = datetime.now(UTC)
    async with session_scope() as session:
        rec = RecommendationRow(
            id=f"rec-rate-limit-{now.timestamp()}",
            symbol="RATE-LIMIT-TEST",
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
            reasons="[]",
            risks="[]",
            created_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        session.add(rec)
        await session.commit()

        service = ApprovalService(session)
        _, plaintext = await service.create_approval(rec.id, _TEST_USER_ID)
        return plaintext


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_decide_endpoint_429s_after_exhausting_the_attempt_budget() -> None:
    settings = get_settings()
    original_hash = settings.app_pin_hash
    settings.app_pin_hash = hash_pin("9999")
    redis = get_redis()

    try:
        await _seed_valid_kakao_session(_TEST_USER_ID)
        token = await _create_approval()
        await redis.delete(f"approval_decide_rate_limit:{token}")

        max_attempts = settings.approval_rate_limit_max_attempts
        async with await _client() as client:
            for _ in range(max_attempts):
                response = await client.post(
                    f"/api/approvals/{token}/decide",
                    json={"decision": "APPROVE", "pin": "0000"},
                    headers={"X-User-Id": _TEST_USER_ID},
                )
                assert response.status_code == 400  # wrong PIN, but under budget

            over_budget = await client.post(
                f"/api/approvals/{token}/decide",
                json={"decision": "APPROVE", "pin": "9999"},  # correct PIN, doesn't matter now
                headers={"X-User-Id": _TEST_USER_ID},
            )
        assert over_budget.status_code == 429
    finally:
        settings.app_pin_hash = original_hash
