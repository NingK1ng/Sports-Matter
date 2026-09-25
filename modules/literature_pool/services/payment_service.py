"""
Payment Service - 会员/打赏支付服务

当前实现：
- YunGouOS 支付宝电脑网站支付（webPay）
- YunGouOS 异步回调验签与订单入账
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from modules.literature_pool.models.payment_order import PaymentOrder
from modules.literature_pool.models.user import User


class PaymentConfigError(ValueError):
    """支付配置错误（缺少商户信息/回调地址等）"""


@dataclass(frozen=True)
class TierInfo:
    tier: str
    amount: Decimal
    body: str
    duration_days: Optional[int]  # None = 不开通/终身（由 tier 判断）


TIER_CATALOG: dict[str, TierInfo] = {
    "monthly": TierInfo(tier="monthly", amount=Decimal("19.90"), body="Sports Matter 月度饲料", duration_days=30),
    "yearly": TierInfo(tier="yearly", amount=Decimal("199.90"), body="Sports Matter 年度饲料", duration_days=365),
    "lifetime": TierInfo(tier="lifetime", amount=Decimal("299.90"), body="Sports Matter 终身饲料", duration_days=None),
    "coffee": TierInfo(tier="coffee", amount=Decimal("0.99"), body="Sports Matter 摸摸鸽子", duration_days=None),
}


class PaymentService:
    """支付服务"""

    PROVIDER = "yungouos"
    CHANNEL = "alipay_webpay"

    def __init__(self, session: AsyncSession):
        self.session = session

    # ==========================================
    # YunGouOS 通用：签名/校验
    # ==========================================
    def _require_yungouos_config(self) -> Tuple[str, str]:
        mch_id = (settings.yungouos_mch_id or "").strip()
        pay_key = (settings.yungouos_pay_key or "").strip()
        if not mch_id:
            raise PaymentConfigError("YUNGOUOS_NOT_CONFIGURED: missing YUNGOUOS_MCH_ID")
        if not pay_key:
            raise PaymentConfigError("YUNGOUOS_NOT_CONFIGURED: missing YUNGOUOS_PAY_KEY")
        return mch_id, pay_key

    def _validate_notify_url(self, notify_url: str) -> None:
        parsed = urlparse(notify_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise PaymentConfigError("YUNGOUOS_NOTIFY_URL_INVALID: must start with http/https")
        if parsed.port is not None:
            raise PaymentConfigError("YUNGOUOS_NOTIFY_URL_INVALID: must not include port")
        if parsed.query:
            raise PaymentConfigError("YUNGOUOS_NOTIFY_URL_INVALID: must not include query params")

    def _md5_upper(self, s: str) -> str:
        return hashlib.md5(s.encode("utf-8")).hexdigest().upper()

    def _yungouos_sign(self, params: Dict[str, Any], required_keys: list[str], pay_key: str) -> str:
        items: list[str] = []
        for key in sorted(required_keys):
            value = params.get(key)
            if value is None:
                continue
            value_str = str(value).strip()
            if value_str == "":
                continue
            items.append(f"{key}={value_str}")
        string_a = "&".join(items)
        string_sign_temp = f"{string_a}&key={pay_key}"
        return self._md5_upper(string_sign_temp)

    # ==========================================
    # 下单：支付宝电脑网站支付（webPay）
    # ==========================================
    def _format_amount(self, amount: Decimal) -> str:
        q = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return format(q, "f")

    def _apply_coupon_discount(
        self, *, amount: Decimal, invite_code: Optional[str]
    ) -> tuple[Decimal, str | None]:
        code = (invite_code or "").strip()
        if not code:
            return amount, None

        expected = (getattr(settings, "payment_coupon_half_code", "") or "").strip()
        enabled = bool(getattr(settings, "payment_coupon_half_enabled", False))
        if enabled and expected and code == expected:
            discounted = (amount * Decimal("0.1")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return discounted, "tenth"

        return amount, None

    async def _create_order_row(self, user_id: int, tier: str, amount: Decimal) -> PaymentOrder:
        out_trade_no = f"SM{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{secrets.token_hex(4)}"
        order = PaymentOrder(
            user_id=user_id,
            out_trade_no=out_trade_no,
            tier=tier,
            amount=amount,
            currency="CNY",
            provider=self.PROVIDER,
            channel=self.CHANNEL,
            status="created",
        )
        self.session.add(order)
        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def create_yungouos_alipay_webpay(
        self,
        user_id: int,
        tier: str,
        invite_code: Optional[str] = None,
    ) -> Tuple[PaymentOrder, str, str]:
        """
        创建 YunGouOS 支付宝电脑网站支付订单

        Returns:
            (order, pay_url, form)
        """
        tier_info = TIER_CATALOG.get(tier)
        if not tier_info:
            raise ValueError(f"INVALID_TIER: {tier}")

        mch_id, pay_key = self._require_yungouos_config()

        # notify_url 要求严格（无端口/无参数），建议生产环境必填
        notify_url = (settings.yungouos_notify_url or "").strip()
        if notify_url:
            self._validate_notify_url(notify_url)

        final_amount, coupon_tag = self._apply_coupon_discount(amount=tier_info.amount, invite_code=invite_code)
        order = await self._create_order_row(user_id=user_id, tier=tier_info.tier, amount=final_amount)

        total_fee = self._format_amount(final_amount)

        payload: Dict[str, Any] = {
            "out_trade_no": order.out_trade_no,
            "total_fee": total_fee,
            "mch_id": mch_id,
            "body": tier_info.body,
        }

        # 可选参数
        if settings.yungouos_alipay_app_id:
            payload["app_id"] = settings.yungouos_alipay_app_id
        if settings.yungouos_return_url:
            payload["return_url"] = settings.yungouos_return_url
        if notify_url:
            payload["notify_url"] = notify_url

        # 附加数据（回调原路返回；不参与签名）
        attach_parts = [f"uid={user_id}", f"tier={tier_info.tier}"]
        if coupon_tag:
            attach_parts.append(f"coupon={coupon_tag}")
        payload["attach"] = ";".join(attach_parts)

        required_keys = ["out_trade_no", "total_fee", "mch_id", "body"]
        payload["sign"] = self._yungouos_sign(payload, required_keys=required_keys, pay_key=pay_key)

        api_base = (settings.yungouos_api_base_url or "https://api.pay.yungouos.com").rstrip("/")
        url = f"{api_base}/api/pay/alipay/webPay"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, data=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            order.status = "failed"
            order.raw_create_response = {"error": str(e)}
            await self.session.commit()
            raise ValueError(f"YUNGOUOS_WEBPAY_REQUEST_FAILED: {type(e).__name__}: {e}") from e

        order.raw_create_response = data
        if int(data.get("code", 1)) != 0:
            order.status = "failed"
            await self.session.commit()
            raise ValueError(f"YUNGOUOS_WEBPAY_FAILED: {data.get('msg') or data}")

        order.status = "pending"
        await self.session.commit()
        await self.session.refresh(order)

        pay_url = ((data.get("data") or {}).get("url") or "").strip()
        form = ((data.get("data") or {}).get("form") or "").strip()
        if not pay_url or not form:
            raise ValueError(f"YUNGOUOS_WEBPAY_INVALID_RESPONSE: {data}")

        return order, pay_url, form

    # ==========================================
    # 回调：异步通知（notify_url）
    # ==========================================
    async def handle_yungouos_notify(self, payload: Dict[str, Any]) -> PaymentOrder:
        mch_id, pay_key = self._require_yungouos_config()

        required_keys = ["code", "orderNo", "outTradeNo", "payNo", "money", "mchId"]
        missing = [k for k in required_keys if not str(payload.get(k, "")).strip()]
        if missing:
            raise ValueError(f"YUNGOUOS_NOTIFY_MISSING_FIELDS: {','.join(missing)}")

        if str(payload.get("mchId")).strip() != mch_id:
            raise ValueError("YUNGOUOS_NOTIFY_MCH_ID_MISMATCH")

        sign = str(payload.get("sign", "")).strip()
        if not sign:
            raise ValueError("YUNGOUOS_NOTIFY_MISSING_SIGN")

        expected_sign = self._yungouos_sign(payload, required_keys=required_keys, pay_key=pay_key)
        if sign.upper() != expected_sign:
            raise ValueError("YUNGOUOS_NOTIFY_BAD_SIGN")

        out_trade_no = str(payload.get("outTradeNo")).strip()
        stmt = select(PaymentOrder).where(PaymentOrder.out_trade_no == out_trade_no)
        result = await self.session.execute(stmt)
        order = result.scalar_one_or_none()
        if not order:
            raise ValueError("YUNGOUOS_NOTIFY_ORDER_NOT_FOUND")

        # 幂等处理：重复回调直接成功返回
        if order.status == "paid":
            return order

        order.external_order_no = str(payload.get("orderNo", "")).strip() or None
        order.external_pay_no = str(payload.get("payNo", "")).strip() or None
        order.external_pay_channel = str(payload.get("payChannel", "")).strip() or None
        order.raw_notify_payload = payload

        callback_amount: Optional[Decimal] = None
        try:
            callback_amount = Decimal(str(payload.get("money"))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except Exception:
            callback_amount = None

        # code: 1 success, 0 failed
        is_success = str(payload.get("code")).strip() == "1"
        if not is_success:
            order.status = "failed"
            await self.session.commit()
            await self.session.refresh(order)
            return order

        if callback_amount is not None:
            order_amount = Decimal(order.amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if callback_amount != order_amount:
                order.status = "failed"
                await self.session.commit()
                await self.session.refresh(order)
                raise ValueError("YUNGOUOS_NOTIFY_AMOUNT_MISMATCH")

        order.status = "paid"
        order.paid_at = datetime.now()

        await self._grant_membership_if_applicable(order)

        await self.session.commit()
        await self.session.refresh(order)
        return order

    async def _grant_membership_if_applicable(self, order: PaymentOrder) -> None:
        if order.tier == "coffee":
            return

        stmt = select(User).where(User.id == order.user_id)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            return

        # 终身会员不再叠加
        if user.membership_is_lifetime:
            return

        now = datetime.now()

        if order.tier == "lifetime":
            user.membership_tier = "lifetime"
            user.membership_is_lifetime = True
            user.membership_started_at = user.membership_started_at or now
            user.membership_expires_at = None
            return

        tier_info = TIER_CATALOG.get(order.tier)
        duration_days = tier_info.duration_days if tier_info else None
        if not duration_days:
            return

        base = now
        if user.membership_expires_at and user.membership_expires_at > now:
            base = user.membership_expires_at

        user.membership_tier = order.tier
        user.membership_started_at = user.membership_started_at or now
        user.membership_expires_at = base + timedelta(days=duration_days)
