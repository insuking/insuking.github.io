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
from sqlalchemy import select
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
from app.approval.execution import (
    ExecutionResult,
    execute_approved_recommendation,
    gather_kis_revalidation_input,
    gather_upbit_revalidation_input,
)
from app.approval.rate_limit import check_and_record_attempt
from app.approval.service import ApprovalDecision, ApprovalService
from app.core.config import get_settings
from app.db.models import Approval
from app.db.models import Recommendation as RecommendationRow
from app.db.redis_client import get_redis
from app.db.session import session_scope
from app.integrations.kakao.auth import KakaoAuth
from app.integrations.kakao.token_store import KakaoTokenStore
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.execution import KisExecutionProvider
from app.integrations.kis.orders import KisOrderClient
from app.integrations.kis.rest_client import KisRestClient
from app.integrations.upbit.auth import UpbitAuth
from app.integrations.upbit.execution import UpbitExecutionProvider
from app.integrations.upbit.orders import UpbitOrderClient
from app.integrations.upbit.rest_client import UpbitRestClient
from app.models.domain import AssetType

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
    execution_outcome: str | None = None
    """Set only for an APPROVE/APPROVE_WITH_AMOUNT_CHANGE decision on a
    STOCK (routed to KIS) or CRYPTO (routed to Upbit) recommendation - see
    `app/approval/execution.py`'s `ExecutionOutcome`. `None` for REJECT/
    HOLD. Toss is not wired to any recommendation's execution bridge yet -
    see that module's own docstring for why STOCK always means KIS here."""
    execution_reasons: list[str] = []


async def _execute_stock_recommendation(
    session: AsyncSession, approval: Approval, recommendation: RecommendationRow
) -> ExecutionResult:
    """Only called for a just-APPROVED STOCK recommendation. Builds a real
    `KisRestClient`/`KisExecutionProvider` and runs the P29 bridge
    (`app/approval/execution.py`). Safe to call even with KIS
    unconfigured or `LIVE_TRADING`/`KIS_PAPER_TRADING` at their defaults -
    those all fail closed (INVALIDATED from unhealthy market data, or
    EXECUTION_FAILED from `LiveTradingDisabledError`), never place a real
    order by accident.
    """
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.kis_rest_base_url, timeout=10.0) as client:
        auth = KisAuth(client=client, settings=settings)
        rest = KisRestClient(client, auth)
        revalidation_data = await gather_kis_revalidation_input(session, rest, approval, recommendation)

        order_client = KisOrderClient(
            client, auth, settings.kis_cano, settings.kis_acnt_prdt_cd, paper_trading=settings.kis_paper_trading
        )
        provider = KisExecutionProvider(order_client, settings=settings)

        return await execute_approved_recommendation(
            session,
            approval,
            recommendation,
            revalidation_data,
            provider.place_order,
            lambda quantity: {"quantity": str(quantity), "price": str(recommendation.entry_low)},
        )


async def _execute_crypto_recommendation(
    session: AsyncSession, approval: Approval, recommendation: RecommendationRow
) -> ExecutionResult:
    """Only called for a just-APPROVED CRYPTO recommendation. Builds a real
    `UpbitRestClient`/`UpbitExecutionProvider` and runs the same P29 bridge
    as `_execute_stock_recommendation()` above. Safe to call even with
    Upbit unconfigured or `LIVE_TRADING` at its default - both fail closed
    (INVALIDATED from unhealthy market data, or EXECUTION_FAILED from
    `LiveTradingDisabledError`), never place a real order by accident.
    Unlike KIS, Upbit has no separate paper-trading switch to also check -
    `LIVE_TRADING` alone gates every mutating call (see
    `app/integrations/upbit/execution.py`'s module docstring).
    """
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.upbit_rest_base_url, timeout=10.0) as client:
        rest = UpbitRestClient(client)
        revalidation_data = await gather_upbit_revalidation_input(session, rest, approval, recommendation)

        auth = UpbitAuth(settings.upbit_access_key, settings.upbit_secret_key)
        order_client = UpbitOrderClient(client, auth)
        provider = UpbitExecutionProvider(order_client, settings=settings)

        return await execute_approved_recommendation(
            session,
            approval,
            recommendation,
            revalidation_data,
            provider.place_order,
            lambda quantity: {
                "ord_type": "limit",
                "volume": str(quantity),
                "price": str(recommendation.entry_low),
            },
        )


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

        if approval.state != "APPROVED":
            return DecideResponse(approval_state=approval.state)

        recommendation_result = await session.execute(
            select(RecommendationRow).where(RecommendationRow.id == approval.recommendation_id)
        )
        recommendation = recommendation_result.scalar_one_or_none()
        if recommendation is None:
            return DecideResponse(approval_state=approval.state)

        if recommendation.asset_type == AssetType.STOCK.value:
            result = await _execute_stock_recommendation(session, approval, recommendation)
        elif recommendation.asset_type == AssetType.CRYPTO.value:
            result = await _execute_crypto_recommendation(session, approval, recommendation)
        else:
            return DecideResponse(approval_state=approval.state)

        return DecideResponse(
            approval_state=result.approval.state,
            execution_outcome=result.outcome.value,
            execution_reasons=result.reasons,
        )
