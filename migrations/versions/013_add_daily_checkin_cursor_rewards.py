"""add daily check-in cursor rewards

Revision ID: 013_add_checkin_rewards
Revises: 012_add_feature_usage_counters
Create Date: 2026-01-02

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "013_add_checkin_rewards"
down_revision: Union[str, None] = "012_add_feature_usage_counters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_checkins",
        sa.Column("user_id", sa.Integer(), nullable=False, comment="用户ID"),
        sa.Column("last_checkin_date", sa.Date(), nullable=True, comment="最后签到日期（Asia/Shanghai）"),
        sa.Column(
            "streak_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="连续签到天数",
        ),
        sa.Column(
            "unlocked_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="已解锁图标数量（0-30）",
        ),
        sa.Column(
            "selected_cursor_id",
            sa.Integer(),
            nullable=True,
            comment="当前选择的鼠标图标ID（1-30）",
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
        sa.PrimaryKeyConstraint("user_id"),
        comment="用户签到状态表（30日连签奖励）",
    )

    op.create_table(
        "user_checkin_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="用户ID"),
        sa.Column("checkin_date", sa.Date(), nullable=False, comment="签到日期（Asia/Shanghai）"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            comment="创建时间",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "checkin_date", name="uq_user_checkin_user_date"),
        comment="用户每日签到事件表",
    )
    op.create_index(
        "idx_user_checkin_events_user_date",
        "user_checkin_events",
        ["user_id", "checkin_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_user_checkin_events_user_date", table_name="user_checkin_events")
    op.drop_table("user_checkin_events")
    op.drop_table("user_checkins")
