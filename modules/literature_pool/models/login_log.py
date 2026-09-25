"""
Login Log Model - 登录日志表
"""
from sqlalchemy import Column, String, Integer, TIMESTAMP, text, Index, ForeignKey
from datetime import datetime

from models.base import Base


class LoginLog(Base):
    """登录日志表"""
    
    __tablename__ = "login_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    
    # 用户关联
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID"
    )
    
    # 登录信息
    ip = Column(String(45), nullable=True, comment="登录IP（IPv4/IPv6）")
    user_agent = Column(String(500), nullable=True, comment="User Agent")
    
    # 时间戳
    login_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="登录时间"
    )
    
    # 索引
    __table_args__ = (
        Index("idx_login_log_user_id", "user_id"),
        Index("idx_login_log_login_at", "login_at"),
    )
    
    def __repr__(self):
        return f"<LoginLog(id={self.id}, user_id={self.user_id}, login_at={self.login_at})>"
