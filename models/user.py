"""
用户数据模型（占位）

⚠️ DEPRECATED: This model is deprecated for authentication purposes.
Use `modules.literature_pool.models.user.User` for all authentication and login code.

阶段3由其他团队实现完整的用户系统
"""

from typing import Optional
from sqlalchemy import String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """用户模型（占位）"""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 基本信息
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # 密码（阶段3实现）
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username})>"


# TODO: 阶段3添加以下模型
# - Subscription（订阅）
# - UserPreference（用户偏好）
# - InviteCode（邀请码）
# - Payment（支付记录）
