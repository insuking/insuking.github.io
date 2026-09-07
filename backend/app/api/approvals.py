"""Approval HTTP API (P13).

Endpoints for the mobile approval page (frontend `/approve/:token` route):
GET to view an approval's current detail, POST to record a decision. See
docs/MASTER_SPEC.md sections C-E for the security model this maps onto.

Auth model (documented choice, not a placeholder): "authenticated user"
means "holds a currently-valid Kakao Login session" -
`KakaoTokenStore.get_valid_access_token` returns non-None for that user_id
(see app/integrations/kakao/token_store.py). This reuses P12's real OAuth
token store rather than inventing a parallel session system. The client
identifies which user it is via the `X-User-Id` header, sourced from
`localStorage` on the frontend after a real Kakao login redirect
(`app/api/auth.py`, P21) populates it - a server-side session/cookie layer
was considered and deliberately not built instead, since it would replace
this already-working design rather than complete it. Rate limiting on
`decide()` (P21, `app/approval/rate_limit.py`) is what actually bounds PIN
brute-forcing here, since nothing about the header itself is a secret.
"""

from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.approval.errors import (
    ApprovalGoneError,
    ApprovalNotAuthenticatedError,
    ApprovalNotFoundError,
    ApprovalUserMismatchError,
    InvalidDecisionError,
    PinIncorrectError,
    PinNotConfiguredError,
)
from app.approval.rate_limit import check_and_record_attempt
from app.approval.service import ApprovalDecision, ApprovalService
from app.core.config import get_settings
from app.db.redis_client import get_redis
from app.db.session import session_scope
from app.integrations.kakao.auth import KakaoAuth
from app.integrations.kakao.token_store import KakaoTokenStore

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


def _confidence_label(score: float) -> str:
    if score >= 80:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    return "LOW"


class ApprovalDetailResponse(BaseModel):
    approval_state: str
    remaining_seconds: int
    symbol: str
    asset_type: str
    entry_low: float
    entry_high: float
    stop_price: float
    t1_price: float
    t1_percent: float
    t2_price: float
    t2_percent: float
    runner_percent: float
    expected_max_loss: float
    risk_reward: float
    score: float
    confidence: str
    reasons: list[str]
    risks: list[str]


class DecideRequest(BaseModel):
    decision: ApprovalDecision
    override_amount: float | None = None
    pin: str | None = None


class DecideResponse(BaseModel):
    approval_state: str


async def _require_authenticated(session: AsyncSession, user_id: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        store = KakaoTokenStore(session, KakaoAuth(client=client))
        token = await store.get_valid_access_token(user_id)
    if token is None:
        raise ApprovalNotAuthenticatedError("No valid Kakao session for this user")


@router.get("/{token}", response_model=ApprovalDetailResponse)
async def get_approval(token: str, x_user_id: str = Header(..., alias="X-User-Id")) -> ApprovalDetailResponse:
    async with session_scope() as session:
        try:
            await _require_authenticated(session, x_user_id)
            service = ApprovalService(session)
            view = await service.open_by_token(token, x_user_id)
        except ApprovalNotAuthenticatedError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ApprovalNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ApprovalUserMismatchError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        rec = view.recommendation
        return ApprovalDetailResponse(
            approval_state=view.approval.state,
            remaining_seconds=view.remaining_seconds,
            symbol=rec.symbol,
            asset_type=rec.asset_type,
            entry_low=rec.entry_low,
            entry_high=rec.entry_high,
            stop_price=rec.stop_price,
            t1_price=rec.t1_price,
            t1_percent=rec.t1_percent,
            t2_price=rec.t2_price,
            t2_percent=rec.t2_percent,
            runner_percent=rec.runner_percent,
            expected_max_loss=rec.expected_max_loss,
            risk_reward=rec.risk_reward,
            score=rec.score,
            confidence=_confidence_label(rec.score),
            reasons=json.loads(rec.reasons),
            risks=json.loads(rec.risks),
        )


@router.post("/{token}/decide", response_model=DecideResponse)
async def decide_approval(
    token: str, body: DecideRequest, x_user_id: str = Header(..., alias="X-User-Id")
) -> DecideResponse:
    settings = get_settings()
    allowed = await check_and_record_attempt(
        get_redis(),
        token,
        max_attempts=settings.approval_rate_limit_max_attempts,
        window_seconds=settings.approval_rate_limit_window_seconds,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many attempts on this approval - try again shortly")

    async with session_scope() as session:
        try:
            await _require_authenticated(session, x_user_id)
            service = ApprovalService(session)
            approval = await service.decide(
                token,
                x_user_id,
                body.decision,
                override_amount=body.override_amount,
                pin=body.pin,
            )
        except ApprovalNotAuthenticatedError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except ApprovalNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ApprovalUserMismatchError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ApprovalGoneError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except InvalidDecisionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PinIncorrectError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PinNotConfiguredError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return DecideResponse(approval_state=approval.state)
