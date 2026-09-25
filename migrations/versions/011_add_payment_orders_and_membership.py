"""add payment orders and membership fields

Revision ID: 011_payment_orders_membership
Revises: 010_add_assistant_query_log
Create Date: 2025-12-23

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "011_payment_orders_membership"
down_revision: Union[str, None] = "010_add_assistant_query_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users: membership fields
    op.add_column(
        "users",
        sa.Column("membership_tier", sa.String(length=20), nullable=True, comment="会员档位"),
    )
    op.add_column(
        "users",
        sa.Column(
            "membership_is_lifetime",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
            comment="是否终身会员",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "membership_started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="会员开始时间",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "membership_expires_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="会员到期时间（终身会员为空）",
        ),
    )

    # payment_orders
    op.create_table(
        "payment_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="订单ID"),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="用户ID"),
        sa.Column("out_trade_no", sa.String(length=64), nullable=False, comment="商户订单号（不可重复）"),
        sa.Column("tier", sa.String(length=20), nullable=False, comment="购买档位"),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False, comment="订单金额（元）"),
        sa.Column(
            "currency",
            sa.String(length=10),
            nullable=False,
            server_default=sa.text("'CNY'"),
            comment="币种",
        ),
        sa.Column("provider", sa.String(length=30), nullable=False, comment="支付服务商：yungouos"),
        sa.Column("channel", sa.String(length=30), nullable=False, comment="支付通道：alipay_webpay"),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'created'"),
            comment="状态：created/pending/paid/failed/canceled",
        ),
        sa.Column("external_order_no", sa.String(length=64), nullable=True, comment="YunGouOS 订单号（orderNo）"),
        sa.Column("external_pay_no", sa.String(length=128), nullable=True, comment="第三方支付单号（payNo）"),
        sa.Column("external_pay_channel", sa.String(length=20), nullable=True, comment="支付渠道：wxpay/alipay"),
        sa.Column("raw_create_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="下单响应原文"),
        sa.Column("raw_notify_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="异步回调原文"),
        sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="支付完成时间"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="更新时间",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("out_trade_no", name="uq_payment_orders_out_trade_no"),
        comment="支付订单表",
    )

    op.create_index("idx_payment_orders_out_trade_no", "payment_orders", ["out_trade_no"])
    op.create_index("idx_payment_orders_user_id", "payment_orders", ["user_id"])
    op.create_index(
        "idx_payment_orders_user_id_created_at",
        "payment_orders",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_payment_orders_status_created_at",
        "payment_orders",
        ["status", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_payment_orders_status_created_at", table_name="payment_orders")
    op.drop_index("idx_payment_orders_user_id_created_at", table_name="payment_orders")
    op.drop_index("idx_payment_orders_user_id", table_name="payment_orders")
    op.drop_index("idx_payment_orders_out_trade_no", table_name="payment_orders")
    op.drop_table("payment_orders")

    op.drop_column("users", "membership_expires_at")
    op.drop_column("users", "membership_started_at")
    op.drop_column("users", "membership_is_lifetime")
    op.drop_column("users", "membership_tier")
