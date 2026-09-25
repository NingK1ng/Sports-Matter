"""
Payment API Schemas
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CreateWebPayRequest(BaseModel):
    """创建 YunGouOS 支付宝电脑网站支付订单"""

    tier: str = Field(..., description="购买档位：monthly/yearly/lifetime/coffee")
    invite_code: Optional[str] = Field(default=None, description="邀请码（暂不启用）")


class CreateWebPayResponse(BaseModel):
    """下单响应"""

    out_trade_no: str
    tier: str
    amount: str
    pay_url: str
    form: str


class PaymentOrderStatusResponse(BaseModel):
    """订单状态查询"""

    out_trade_no: str
    tier: str
    amount: str
    status: str
    paid_at: Optional[datetime] = None

