"""
User Model - 用户表

支持微信登录和活跃度跟踪
"""
from sqlalchemy import Column, String, Integer, TIMESTAMP, Boolean, text
from datetime import datetime

from models.base import Base


class User(Base):
    """用户表"""
    
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="用户ID")
    
    # 微信登录信息
    wechat_openid = Column(String(64), unique=True, nullable=False, index=True, comment="微信OpenID")
    wechat_unionid = Column(String(64), nullable=True, index=True, comment="微信UnionID（可选）")
    wechat_nickname = Column(String(100), nullable=True, comment="微信昵称")
    wechat_avatar = Column(String(500), nullable=True, comment="微信头像URL")
    
    # 登录来源和状态
    login_source = Column(String(20), nullable=False, default="wechat_open", comment="登录来源：wechat_open/wechat_mp")
    is_active = Column(Boolean, nullable=False, default=True, comment="账号是否激活")
    
    # 活跃度追踪
    last_login_at = Column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="最后登录时间（用于活跃度判断）"
    )
    
    # 订阅状态（预留字段，用于未来公众号推送）
    subscribe_status = Column(Boolean, nullable=False, default=False, comment="是否关注公众号")

    # 会员信息（站内会员/打赏，不影响“访客可用全部功能”的公共访问逻辑）
    membership_tier = Column(
        String(20),
        nullable=True,
        comment="会员档位：monthly/yearly/lifetime（coffee 为打赏不写入）",
    )
    membership_is_lifetime = Column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否终身会员",
    )
    membership_started_at = Column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="会员开始时间",
    )
    membership_expires_at = Column(
        TIMESTAMP(timezone=True),
        nullable=True,
        comment="会员到期时间（终身会员为空）",
    )

    # 时间戳
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="创建时间"
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=datetime.now,
        comment="更新时间"
    )
    
    def __repr__(self):
        return f"<User(id={self.id}, openid={self.wechat_openid[:8]}..., nickname={self.wechat_nickname})>"
