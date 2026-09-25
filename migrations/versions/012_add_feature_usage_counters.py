"""add feature usage counters

Revision ID: 012_add_feature_usage_counters
Revises: 011_payment_orders_membership
Create Date: 2025-12-23

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "012_add_feature_usage_counters"
down_revision: Union[str, None] = "011_payment_orders_membership"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feature_usage_counters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="用户ID"),
        sa.Column("feature_key", sa.String(length=64), nullable=False, comment="功能标识"),
        sa.Column("week_start", sa.Date(), nullable=False, comment="周起始日期（周一）"),
        sa.Column(
            "count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="本周已使用次数",
        ),
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
        sa.UniqueConstraint(
            "user_id",
            "feature_key",
            "week_start",
            name="uq_feature_usage_user_feature_week",
        ),
        comment="功能试用次数计数器（按周）",
    )

    op.create_index(
        "idx_feature_usage_feature_week",
        "feature_usage_counters",
        ["feature_key", "week_start"],
    )
    op.create_index(
        "idx_feature_usage_user_week",
        "feature_usage_counters",
        ["user_id", "week_start"],
    )


def downgrade() -> None:
    op.drop_index("idx_feature_usage_user_week", table_name="feature_usage_counters")
    op.drop_index("idx_feature_usage_feature_week", table_name="feature_usage_counters")
    op.drop_table("feature_usage_counters")
