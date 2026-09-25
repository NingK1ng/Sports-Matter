"""add membership activation codes

Revision ID: 014_activation_codes
Revises: 013_add_checkin_rewards
Create Date: 2026-01-03

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014_activation_codes"
down_revision: Union[str, None] = "013_add_checkin_rewards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "membership_activation_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("code_hash", sa.String(length=64), nullable=False, comment="激活码Hash(sha256)"),
        sa.Column(
            "tier",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'lifetime'"),
            comment="开通档位：lifetime",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
            comment="是否启用",
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="过期时间（可选）"),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True, comment="使用时间（为空表示未使用）"),
        sa.Column("used_by_user_id", sa.Integer(), nullable=True, comment="使用者用户ID"),
        sa.Column("note", sa.String(length=200), nullable=True, comment="备注（可选）"),
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
        sa.ForeignKeyConstraint(["used_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash", name="uq_membership_activation_codes_code_hash"),
        comment="一次性会员激活码表（仅保存Hash，避免明文泄露）",
    )

    op.create_index(
        "idx_membership_activation_codes_code_hash",
        "membership_activation_codes",
        ["code_hash"],
    )
    op.create_index(
        "idx_membership_activation_codes_used_by_user_id",
        "membership_activation_codes",
        ["used_by_user_id"],
    )
    op.create_index(
        "idx_membership_activation_codes_active_used",
        "membership_activation_codes",
        ["is_active", "used_at"],
    )
    op.create_index(
        "idx_membership_activation_codes_expires_at",
        "membership_activation_codes",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_membership_activation_codes_expires_at", table_name="membership_activation_codes")
    op.drop_index("idx_membership_activation_codes_active_used", table_name="membership_activation_codes")
    op.drop_index("idx_membership_activation_codes_used_by_user_id", table_name="membership_activation_codes")
    op.drop_index("idx_membership_activation_codes_code_hash", table_name="membership_activation_codes")
    op.drop_table("membership_activation_codes")

