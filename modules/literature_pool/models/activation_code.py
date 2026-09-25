"""
MembershipActivationCode Model - 一次性会员激活码

用于发放「一次性」终身会员激活码：
- 数据库仅保存 code_hash（避免明文泄露）
- 兑换成功后标记 used_at / used_by_user_id，确保不可重复使用
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    TIMESTAMP,
    text,
)

from models.base import Base


class MembershipActivationCode(Base):
    """一次性会员激活码表"""

    __tablename__ = "membership_activation_codes"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    # sha256(lower(code)) hex string (64 chars)
    code_hash = Column(String(64), nullable=False, unique=True, index=True, comment="激活码Hash(sha256)")

    tier = Column(
        String(20),
        nullable=False,
        server_default=text("'lifetime'"),
        comment="开通档位：lifetime",
    )
    is_active = Column(Boolean, nullable=False, server_default=text("TRUE"), comment="是否启用")

    expires_at = Column(TIMESTAMP(timezone=True), nullable=True, comment="过期时间（可选）")

    used_at = Column(TIMESTAMP(timezone=True), nullable=True, comment="使用时间（为空表示未使用）")
    used_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="使用者用户ID",
    )

    note = Column(String(200), nullable=True, comment="备注（可选）")

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
        Index("idx_activation_codes_active_used", "is_active", "used_at"),
        Index("idx_activation_codes_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<MembershipActivationCode(id={self.id}, used_at={self.used_at}, active={self.is_active})>"

