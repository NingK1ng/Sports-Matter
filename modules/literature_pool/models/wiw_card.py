"""
Pool WiW Card Model - WiW卡片映射表

仅存储wiw_result_id引用，不重复存储JSON
"""
from sqlalchemy import Column, String, Integer, TIMESTAMP, text, Index, ForeignKey, CheckConstraint
from datetime import datetime

from models.base import Base


class PoolWiWCard(Base):
    """WiW卡片映射表"""
    
    __tablename__ = "pool_wiw_cards"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    
    # 订阅关联
    subscription_id = Column(
        Integer,
        ForeignKey("pool_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="订阅ID"
    )
    
    # 轨道标识
    track = Column(
        String(20),
        nullable=False,
        index=True,
        comment="轨道类型：stream（模块1）/ journals（模块2）"
    )
    
    # WiW结果引用
    wiw_result_id = Column(
        Integer,
        ForeignKey("wiw_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="WiW结果ID（关联模块3的wiw_results表）"
    )
    
    # 源文献PMID
    source_pmid = Column(String(20), nullable=False, index=True, comment="源文献PMID")
    
    # 过期时间
    generated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="生成时间"
    )
    expires_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        comment="过期时间（generated_at + 7天）"
    )
    
    # 索引
    __table_args__ = (
        Index("idx_wiw_card_subscription_id", "subscription_id"),
        Index("idx_wiw_card_track", "track"),
        Index("idx_wiw_card_wiw_result_id", "wiw_result_id"),
        Index("idx_wiw_card_expires_at", "expires_at"),
        Index("idx_wiw_card_subscription_track", "subscription_id", "track"),
        CheckConstraint("track IN ('stream', 'journals')", name="check_wiw_card_track"),
    )
    
    def __repr__(self):
        return f"<PoolWiWCard(id={self.id}, subscription_id={self.subscription_id}, track={self.track}, wiw_result_id={self.wiw_result_id})>"
