"""Position detail + manual controls API (P46).

Extends what `app/api/dashboard.py`'s `/positions/live-prices` (P42) and
`/summary` already expose (list + live price) with per-position detail
and the two real actions the SmartCoin mockups' "포지션 관리"/"비상정지와
복구" screens need: pausing Guardian's automatic management, and manually
closing a position right now. Both require an authenticated Kakao session
(`_require_authenticated`, reused from `app/api/approvals.py`) - the same
"explicit human in the loop every time" gate `app/api/dashboard.py`'s
manual emergency-stop already applies to a real action taken in the
user's name.

`POST /{id}/close` is the first thing in this project that places a real
SELL order against an existing position (see
`app/positions/manual_close.py`'s own docstring) - it is gated exactly
like a BUY order already is: `ExecutionProvider.place_order()`'s
`_require_live_trading()` check underneath, with `LIVE_TRADING` staying a
server-only `.env` setting no UI can flip. In demo mode (the default)
this endpoint always fails closed with a 409 naming that fact, never a
fabricated "closed" response.

T1/T2 "progress" is deliberately shown via `Position.state` (already
accurately fill-derived by `PartialProfitService`, see
`app/partial_profit/accounting.py`) plus each `ProtectiveOrder`'s target
price - not a computed fill percentage. `Position` has no `trade_plan_id`
foreign key, so there is no reliable way to look up *which* `TradePlan`
(and therefore which `t1_percent`/`t2_percent`) produced a given open
position; inventing a symbol-based guess would fabricate a precision this
project's schema doesn't actually have. `state` and each protective
order's `trigger_price`/`active` flag are the honest, real signals this
endpoint can expose today.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.approvals import _require_authenticated
from app.approval.errors import ApprovalNotAuthenticatedError
from app.core.config import get_settings
from app.db.models import Position as PositionRow
from app.db.models import ProtectiveOrder as ProtectiveOrderRow
from app.db.session import session_scope
from app.execution.errors import ExecutionError, LiveTradingDisabledError
from app.integrations.kis.auth import KisAuth
from app.integrations.kis.errors import KisApiError
from app.integrations.kis.execution import KisExecutionProvider
from app.integrations.kis.orders import ORDER_DIVISION_MARKET, KisOrderClient
from app.integrations.kis.rest_client import KisRestClient
from app.integrations.upbit.auth import UpbitAuth
from app.integrations.upbit.errors import UpbitApiError
from app.integrations.upbit.execution import UpbitExecutionProvider
from app.integrations.upbit.orders import UpbitOrderClient
from app.integrations.upbit.rest_client import UpbitRestClient
from app.models.domain import AssetType
from app.positions.manual_close import ManualCloseResult, close_position_market

router = APIRouter(prefix="/api/positions", tags=["positions"])


class ProtectiveOrderOut(BaseModel):
    kind: str
    trigger_price: float
    quantity: float
    active: bool


class PositionDetailOut(BaseModel):
    id: str
    symbol: str
    asset_type: str
    state: str
    quantity: float
    avg_entry_price: float
    stop_price: float
    guardian_active: bool
    opened_at: str
    updated_at: str
    current_price: float | None
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    protective_orders: list[ProtectiveOrderOut]


async def _load_position(session: AsyncSession, position_id: str) -> PositionRow:
    position = await session.get(PositionRow, position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="포지션을 찾을 수 없습니다.")
    return position


async def _fetch_kis_current_price(position: PositionRow) -> float | None:
    settings = get_settings()
    if not settings.kis_configured:
        return None
    try:
        async with httpx.AsyncClient(base_url=settings.kis_rest_base_url, timeout=10.0) as client:
            kis_auth = KisAuth(client=client, settings=settings)
            kis_rest = KisRestClient(client, kis_auth)
            quote = await kis_rest.get_quote(position.symbol)
            return quote.price
    except (KisApiError, httpx.HTTPError, KeyError, ValueError):
        return None


async def _fetch_upbit_current_price(position: PositionRow) -> float | None:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(base_url=settings.upbit_rest_base_url, timeout=10.0) as client:
            upbit_rest = UpbitRestClient(client)
            return await upbit_rest.get_ticker_price(position.symbol)
    except (UpbitApiError, httpx.HTTPError, KeyError, ValueError):
        return None


async def _fetch_current_price(position: PositionRow) -> float | None:
    if position.asset_type == AssetType.STOCK.value:
        return await _fetch_kis_current_price(position)
    return await _fetch_upbit_current_price(position)


def _to_detail(position: PositionRow, current_price: float | None, orders: list[ProtectiveOrderRow]) -> PositionDetailOut:
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    if current_price is not None:
        unrealized_pnl = (current_price - position.avg_entry_price) * position.quantity
        if position.avg_entry_price > 0:
            unrealized_pnl_pct = (current_price - position.avg_entry_price) / position.avg_entry_price * 100

    return PositionDetailOut(
        id=position.id,
        symbol=position.symbol,
        asset_type=position.asset_type,
        state=position.state,
        quantity=position.quantity,
        avg_entry_price=position.avg_entry_price,
        stop_price=position.stop_price,
        guardian_active=position.guardian_active,
        opened_at=position.opened_at.isoformat(),
        updated_at=position.updated_at.isoformat(),
        current_price=current_price,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        protective_orders=[
            ProtectiveOrderOut(kind=o.kind, trigger_price=o.trigger_price, quantity=o.quantity, active=o.active)
            for o in orders
        ],
    )


@router.get("/{position_id}", response_model=PositionDetailOut)
async def get_position_detail(position_id: str) -> PositionDetailOut:
    """P46: the 포지션 관리 detail screen - one real live quote (same
    per-request-cost reasoning as `/positions/live-prices`) plus this
    position's real protective orders (STOP/T1/T2 target prices)."""
    async with session_scope() as session:
        position = await _load_position(session, position_id)
        orders_result = await session.execute(
            select(ProtectiveOrderRow).where(ProtectiveOrderRow.position_id == position_id)
        )
        orders = list(orders_result.scalars().all())

    current_price = await _fetch_current_price(position)
    return _to_detail(position, current_price, orders)


class GuardianToggleRequest(BaseModel):
    active: bool


class GuardianToggleOut(BaseModel):
    id: str
    guardian_active: bool


@router.post("/{position_id}/guardian", response_model=GuardianToggleOut)
async def set_guardian_active(
    position_id: str, body: GuardianToggleRequest, x_user_id: str = Header(..., alias="X-User-Id")
) -> GuardianToggleOut:
    """P46: the "자동관리 일시정지" toggle - flips the one real flag
    `app/guardian/service.py:93` already checks (`if not position.
    guardian_active: return GUARDIAN_INACTIVE`) before doing anything else
    for this position, so a paused position genuinely stops receiving
    trailing-stop tightening and failed-breakout exits, not just a label
    change in the UI."""
    async with session_scope() as session:
        try:
            await _require_authenticated(session, x_user_id)
        except ApprovalNotAuthenticatedError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        position = await _load_position(session, position_id)
        position.guardian_active = body.active
        await session.commit()
        return GuardianToggleOut(id=position.id, guardian_active=position.guardian_active)


class ManualCloseOut(BaseModel):
    id: str
    state: str
    order_id: str
    order_status: str


async def _place_close_order(session: AsyncSession, position: PositionRow, quantity: float) -> ManualCloseOut:
    if position.asset_type == AssetType.STOCK.value:
        result = await _close_via_kis(session, position)
    else:
        result = await _close_via_upbit(session, position)

    return ManualCloseOut(
        id=result.position.id,
        state=result.position.state,
        order_id=result.order.id,
        order_status=result.order.status,
    )


async def _close_via_kis(session: AsyncSession, position: PositionRow) -> ManualCloseResult:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.kis_rest_base_url, timeout=10.0) as client:
        kis_auth = KisAuth(client=client, settings=settings)
        order_client = KisOrderClient(
            client,
            kis_auth,
            settings.kis_cano,
            settings.kis_acnt_prdt_cd,
            paper_trading=settings.kis_paper_trading,
        )
        provider = KisExecutionProvider(order_client, settings=settings)
        return await close_position_market(
            session,
            position,
            provider.place_order,
            lambda qty: {"quantity": str(qty), "order_division": ORDER_DIVISION_MARKET},
        )


async def _close_via_upbit(session: AsyncSession, position: PositionRow) -> ManualCloseResult:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.upbit_rest_base_url, timeout=10.0) as client:
        upbit_auth = UpbitAuth(settings.upbit_access_key, settings.upbit_secret_key)
        order_client = UpbitOrderClient(client, upbit_auth)
        provider = UpbitExecutionProvider(order_client, settings=settings)
        return await close_position_market(
            session,
            position,
            provider.place_order,
            lambda qty: {"ord_type": "market", "volume": str(qty)},
        )


@router.post("/{position_id}/close", response_model=ManualCloseOut)
async def close_position(position_id: str, x_user_id: str = Header(..., alias="X-User-Id")) -> ManualCloseOut:
    """P46: "즉시 청산" - places one real market SELL order for this
    position's full remaining quantity right now. Kakao-session-gated the
    same way `activate_emergency_stop()` is; the frontend additionally
    requires a hold-to-confirm gesture before ever calling this, but that
    is a UI-level friction pattern, not this endpoint's safety boundary -
    the real boundary is `LIVE_TRADING`, checked below."""
    async with session_scope() as session:
        try:
            await _require_authenticated(session, x_user_id)
        except ApprovalNotAuthenticatedError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        position = await _load_position(session, position_id)
        if position.quantity <= 0:
            raise HTTPException(status_code=409, detail="이미 종료된 포지션입니다.")

        try:
            return await _place_close_order(session, position, position.quantity)
        except LiveTradingDisabledError as exc:
            raise HTTPException(
                status_code=409,
                detail="LIVE_TRADING이 비활성화되어 있어 실거래 주문을 낼 수 없습니다 (데모 모드).",
            ) from exc
        except ExecutionError as exc:
            raise HTTPException(status_code=502, detail=f"주문 실행에 실패했습니다: {exc}") from exc
