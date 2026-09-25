"""
PaymentOrder Model - 支付订单表

用于记录站内会员/打赏的支付订单，并对接 YunGouOS 回调完成入账。
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    TIMESTAMP,
    ForeignKey,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from models.base import Base


class PaymentOrder(Base):
    """支付订单表"""

    __tablename__ = "payment_orders"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="订单ID")

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID",
    )

    # 站内订单信息
    out_trade_no = Column(
        String(64), nullable=False, unique=True, index=True, comment="商户订单号（不可重复）"
    )
    tier = Column(String(20), nullable=False, comment="购买档位：monthly/yearly/lifetime/coffee")
    amount = Column(Numeric(10, 2), nullable=False, comment="订单金额（元）")
    currency = Column(String(10), nullable=False, server_default=text("'CNY'"), comment="币种")

    # 支付渠道（当前仅 YunGouOS / 支付宝 webPay）
    provider = Column(String(30), nullable=False, comment="支付服务商：yungouos")
    channel = Column(String(30), nullable=False, comment="支付通道：alipay_webpay")

    status = Column(
        String(20),
        nullable=False,
        server_default=text("'created'"),
        comment="状态：created/pending/paid/failed/canceled",
    )

    # 第三方返回/回调
    external_order_no = Column(String(64), nullable=True, comment="YunGouOS 订单号（orderNo）")
    external_pay_no = Column(String(128), nullable=True, comment="第三方支付单号（payNo）")
    external_pay_channel = Column(String(20), nullable=True, comment="支付渠道：wxpay/alipay")

    raw_create_response = Column(JSONB, nullable=True, comment="下单响应原文")
    raw_notify_payload = Column(JSONB, nullable=True, comment="异步回调原文")

    paid_at = Column(TIMESTAMP(timezone=True), nullable=True, comment="支付完成时间")

    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="创建时间",
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=datetime.now,
        comment="更新时间",
    )

    __table_args__ = (
        Index("idx_payment_orders_user_id_created_at", "user_id", "created_at"),
        Index("idx_payment_orders_status_created_at", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<PaymentOrder(id={self.id}, out_trade_no={self.out_trade_no}, status={self.status})>"

