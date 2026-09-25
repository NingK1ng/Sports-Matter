"""
Pool Subscription Model - 订阅条目表

每个用户最多3个订阅条目
"""
from sqlalchemy import Column, String, Integer, TIMESTAMP, text, Index, ForeignKey, CheckConstraint
from datetime import datetime

from models.base import Base


class PoolSubscription(Base):
    """订阅条目表"""
    
    __tablename__ = "pool_subscriptions"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="订阅ID")
    
    # 用户关联
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID"
    )
    
    # 订阅标题和查询
    title = Column(String(200), nullable=False, comment="订阅标题（用户自定义）")
    query_text = Column(String(500), nullable=False, comment="原始查询文本（用户输入的关键词）")
    
    # 订阅状态
    is_active = Column(Integer, nullable=False, default=1, comment="是否激活（1=激活，0=暂停）")
    
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
    
    # 索引
    __table_args__ = (
        Index("idx_subscription_user_id", "user_id"),
        Index("idx_subscription_created_at", "created_at"),
        CheckConstraint("is_active IN (0, 1)", name="check_subscription_is_active"),
    )
    
    def __repr__(self):
        return f"<PoolSubscription(id={self.id}, user_id={self.user_id}, title={self.title})>"
