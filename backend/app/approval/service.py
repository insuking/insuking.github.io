"""Secure approval service (P13).

Implements docs/MASTER_SPEC.md sections C-E: approval creation with a
single-use, short-TTL token (hash only, see tokens.py), the
CREATED -> NOTIFIED -> OPENED -> {APPROVED, REJECTED, EXPIRED, INVALIDATED,
BLOCKED_BY_RISK} -> EXECUTED lifecycle, and an `approval_events` audit trail
for every transition. `HOLD` (보류) is deliberately not a state transition -
it means "come back later", so it's logged as an event without changing
`Approval.state` or consuming the token, since the user can still act on it
before the TTL runs out.

Approving or rejecting is terminal and consumes the token (docs/MASTER_SPEC.md
section D: "reuse returns HTTP 410" - see app/api/approvals.py for the HTTP
mapping of `ApprovalGoneError`). Viewing (`open_by_token`) never raises for
an already-terminal or expired approval - the frontend needs to render "이미
처리됨"/"만료됨" from a normal response, not an error page; only the
*mutating* `decide()` call enforces one-time use.

This module only ever produces an `APPROVED`/`REJECTED` *decision* - per
docs/MASTER_SPEC.md's "Approval != Guaranteed Order", nothing here places an
order. P14's revalidation and P15's execution providers are what turn an
approval into (or out of) a real trade.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.approval import pin as pin_module
from app.approval.errors import (
    ApprovalGoneError,
    ApprovalNotFoundError,
    ApprovalUserMismatchError,
    InvalidDecisionError,
)
from app.approval.tokens import generate_token, hash_token
from app.core.config import Settings, get_settings
from app.db.models import Approval, ApprovalEvent
from app.db.models import Recommendation as RecommendationRow
from app.integrations.kakao.errors import KakaoNotificationError
from app.integrations.kakao.notify import KakaoNotifier

DEFAULT_TOKEN_TTL_SECONDS = 180  # within docs/MASTER_SPEC.md's 120-300s window

TERMINAL_STATES = frozenset(
    {"APPROVED", "REJECTED", "EXPIRED", "INVALIDATED", "EXECUTED", "BLOCKED_BY_RISK"}
)


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    APPROVE_WITH_AMOUNT_CHANGE = "APPROVE_WITH_AMOUNT_CHANGE"
    HOLD = "HOLD"
    REJECT = "REJECT"


_DECISION_TARGET_STATE = {
    ApprovalDecision.APPROVE: "APPROVED",
    ApprovalDecision.APPROVE_WITH_AMOUNT_CHANGE: "APPROVED",
    ApprovalDecision.REJECT: "REJECTED",
}


@dataclass
class ApprovalView:
    approval: Approval
    recommendation: RecommendationRow
    remaining_seconds: int


class ApprovalService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self._session = session
        self.settings = settings or get_settings()

    # -- creation / notification -------------------------------------

    async def create_approval(
        self,
        recommendation_id: str,
        user_id: str,
        ttl_seconds: int | None = None,
    ) -> tuple[Approval, str]:
        """Returns `(approval, plaintext_token)` - the plaintext is handed
        back exactly once, to build the approval link; only its hash is
        stored."""
        plaintext, token_hash = generate_token()
        now = datetime.now(UTC)
        ttl = ttl_seconds if ttl_seconds is not None else self.settings.approval_token_ttl_seconds
        approval = Approval(
            id=str(uuid.uuid4()),
            recommendation_id=recommendation_id,
            user_id=user_id,
            state="CREATED",
            token_hash=token_hash,
            created_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
        self._session.add(approval)
        await self._record_event(approval.id, from_state=None, to_state="CREATED", actor="system")
        await self._session.commit()
        return approval, plaintext

    async def notify(
        self,
        approval: Approval,
        recommendation: RecommendationRow,
        plaintext_token: str,
        notifier: KakaoNotifier,
        access_token: str,
    ) -> bool:
        """Best-effort KakaoTalk 'send to me' with the approval link.

        Returns whether the send succeeded. Per
        app/integrations/kakao/notify.py's module docstring, a failed send
        must never block the approval from existing - this catches
        `KakaoNotificationError` rather than propagating it, and simply
        leaves `Approval.state`/`notified_at` unchanged on failure so the
        approval stays visible in-app regardless.
        """
        approval_url = f"{self.settings.approval_base_url.rstrip('/')}/approve/{plaintext_token}"
        remaining = max(0, int((approval.expires_at - datetime.now(UTC)).total_seconds()))
        message = (
            f"{recommendation.symbol} 매수 추천 (점수 {round(recommendation.score)}) - "
            f"{remaining}초 내 확인하세요"
        )
        try:
            await notifier.send_approval_link(access_token, approval_url, message)
        except KakaoNotificationError:
            return False

        approval.notified_at = datetime.now(UTC)
        await self._transition(approval, "NOTIFIED", actor="system")
        await self._session.commit()
        return True

    # -- viewing --------------------------------------------------------

    async def open_by_token(self, plaintext_token: str, user_id: str) -> ApprovalView:
        approval = await self._find_by_token(plaintext_token)
        if approval.user_id != user_id:
            raise ApprovalUserMismatchError("This approval belongs to a different user")

        now = datetime.now(UTC)
        if approval.state not in TERMINAL_STATES and now >= approval.expires_at:
            await self._transition(approval, "EXPIRED", actor="system")
            await self._session.commit()
        elif approval.state in ("CREATED", "NOTIFIED"):
            approval.opened_at = approval.opened_at or now
            await self._transition(approval, "OPENED", actor=user_id)
            await self._session.commit()

        recommendation = await self._get_recommendation(approval.recommendation_id)
        remaining = max(0, int((approval.expires_at - now).total_seconds()))
        return ApprovalView(approval=approval, recommendation=recommendation, remaining_seconds=remaining)

    # -- deciding ---------------------------------------------------------

    async def decide(
        self,
        plaintext_token: str,
        user_id: str,
        decision: ApprovalDecision,
        override_amount: float | None = None,
        pin: str | None = None,
    ) -> Approval:
        approval = await self._find_by_token(plaintext_token)
        if approval.user_id != user_id:
            raise ApprovalUserMismatchError("This approval belongs to a different user")

        now = datetime.now(UTC)
        if approval.state not in TERMINAL_STATES and now >= approval.expires_at:
            await self._transition(approval, "EXPIRED", actor="system")
            await self._session.commit()

        if approval.state in TERMINAL_STATES:
            raise ApprovalGoneError(f"This approval is already {approval.state} and cannot be changed")

        if decision == ApprovalDecision.APPROVE_WITH_AMOUNT_CHANGE and (
            override_amount is None or override_amount <= 0
        ):
            raise InvalidDecisionError("override_amount must be a positive number for this decision")

        if decision == ApprovalDecision.HOLD:
            await self._record_event(
                approval.id, approval.state, approval.state, actor=user_id, detail={"decision": "HOLD"}
            )
            await self._session.commit()
            return approval

        detail: dict[str, object] = {}
        if decision in (ApprovalDecision.APPROVE, ApprovalDecision.APPROVE_WITH_AMOUNT_CHANGE):
            # PIN re-check per docs/MASTER_SPEC.md section C - required before
            # any decision that moves toward an order; REJECT/HOLD need no
            # re-check since they can't lead to a trade.
            pin_module.verify_pin(pin or "", self.settings)
            if decision == ApprovalDecision.APPROVE_WITH_AMOUNT_CHANGE:
                detail["override_amount"] = override_amount

        target_state = _DECISION_TARGET_STATE[decision]
        approval.decided_at = now
        await self._transition(approval, target_state, actor=user_id, detail=detail or None)
        await self._session.commit()
        return approval

    async def apply_revalidation_result(
        self, approval: Approval, verdict: str, reasons: list[str] | None = None
    ) -> None:
        """Applies a P14 revalidation verdict. `VALID` is a no-op - approval
        stays `APPROVED` until P15 actually places (or fails to place) the
        order. `INVALIDATED`/`EXPIRED` transition the approval even though
        it was already approved (docs/MASTER_SPEC.md section F: "A failure
        yields TRADE_INVALIDATED even though the approval was received").
        """
        if verdict == "VALID":
            return
        detail: dict[str, object] | None = {"reasons": reasons} if reasons else None
        await self._transition(approval, verdict, actor="system", detail=detail)
        await self._session.commit()

    # -- internals --------------------------------------------------------

    async def _find_by_token(self, plaintext_token: str) -> Approval:
        candidate_hash = hash_token(plaintext_token)
        result = await self._session.execute(select(Approval).where(Approval.token_hash == candidate_hash))
        approval = result.scalar_one_or_none()
        if approval is None:
            raise ApprovalNotFoundError("No approval matches this token")
        return approval

    async def _get_recommendation(self, recommendation_id: str) -> RecommendationRow:
        result = await self._session.execute(
            select(RecommendationRow).where(RecommendationRow.id == recommendation_id)
        )
        recommendation = result.scalar_one_or_none()
        if recommendation is None:
            raise ApprovalNotFoundError("Recommendation for this approval no longer exists")
        return recommendation

    async def _transition(
        self, approval: Approval, to_state: str, actor: str, detail: dict[str, object] | None = None
    ) -> None:
        from_state = approval.state
        approval.state = to_state
        await self._record_event(approval.id, from_state, to_state, actor, detail)

    async def _record_event(
        self,
        approval_id: str,
        from_state: str | None,
        to_state: str,
        actor: str,
        detail: dict[str, object] | None = None,
    ) -> None:
        event = ApprovalEvent(
            id=str(uuid.uuid4()),
            approval_id=approval_id,
            from_state=from_state,
            to_state=to_state,
            actor=actor,
            detail=json.dumps(detail) if detail else None,
            created_at=datetime.now(UTC),
        )
        self._session.add(event)
