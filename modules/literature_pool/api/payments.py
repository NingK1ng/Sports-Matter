"""
Payments API - 会员/打赏支付

当前仅实现：
- YunGouOS 支付宝电脑网站支付（webPay）
- YunGouOS 异步回调（notify_url）
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.literature_pool.api.auth import get_current_user_id, require_login_user
from modules.literature_pool.models.payment_order import PaymentOrder
from modules.literature_pool.schemas.payment import (
    CreateWebPayRequest,
    CreateWebPayResponse,
    PaymentOrderStatusResponse,
)
from modules.literature_pool.services.payment_service import PaymentConfigError, PaymentService


router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("/yungouos/alipay/webpay", response_model=CreateWebPayResponse)
async def create_yungouos_alipay_webpay(
    data: CreateWebPayRequest,
    user=Depends(require_login_user),
    db: AsyncSession = Depends(get_db),
):
    """
    创建 YunGouOS 支付宝电脑网站支付订单
    """
    service = PaymentService(db)
    try:
        order, pay_url, form = await service.create_yungouos_alipay_webpay(
            user_id=user.id,
            tier=data.tier,
            invite_code=data.invite_code,
        )
    except PaymentConfigError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return CreateWebPayResponse(
        out_trade_no=order.out_trade_no,
        tier=order.tier,
        amount=str(order.amount),
        pay_url=pay_url,
        form=form,
    )


@router.get("/orders/{out_trade_no}", response_model=PaymentOrderStatusResponse)
async def get_payment_order_status(
    out_trade_no: str,
    current_user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    查询订单状态（仅允许订单所属用户查询）
    """
    stmt = select(PaymentOrder).where(PaymentOrder.out_trade_no == out_trade_no)
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="ORDER_NOT_FOUND")
    if order.user_id != current_user_id:
        raise HTTPException(status_code=403, detail="FORBIDDEN")

    return PaymentOrderStatusResponse(
        out_trade_no=order.out_trade_no,
        tier=order.tier,
        amount=str(order.amount),
        status=order.status,
        paid_at=order.paid_at,
    )


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (payload or {}).items():
        if v is None:
            continue
        out[str(k)] = str(v)
    return out


@router.post("/yungouos/notify")
async def yungouos_notify(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    YunGouOS 异步回调（notify_url）

    - 不做登录校验（第三方服务器回调）
    - 返回 200 即视为接收成功（建议返回文本 success）
    """
    payload: Dict[str, Any] = {}
    try:
        form = await request.form()
        payload = dict(form)
    except Exception:
        try:
            payload = await request.json()
        except Exception:
            payload = {}

    service = PaymentService(db)
    try:
        await service.handle_yungouos_notify(_normalize_payload(payload))
    except PaymentConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PlainTextResponse("success")


@router.get("/yungouos/return")
async def yungouos_return(request: Request, db: AsyncSession = Depends(get_db)):
    """
    YunGouOS 同步回调（return_url）

    该回调来自用户浏览器跳转，主要用于体验；最终入账以 notify_url 为准。
    """
    payload = _normalize_payload(dict(request.query_params))

    service = PaymentService(db)
    try:
        await service.handle_yungouos_notify(payload)
    except Exception:
        # 同步跳转不阻塞用户体验，忽略异常
        pass

    return RedirectResponse(url="/")
