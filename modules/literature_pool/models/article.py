"""
Pool Article Model - 文献池表（模块1轨道）

存储订阅检索到的文献候选集
"""
from sqlalchemy import Column, String, Integer, TIMESTAMP, text, Index, ForeignKey, UniqueConstraint
from datetime import datetime

from models.base import Base


class PoolArticle(Base):
    """文献池表（模块1轨道）"""
    
    __tablename__ = "pool_articles_stream"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    
    # 订阅关联
    subscription_id = Column(
        Integer,
        ForeignKey("pool_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="订阅ID"
    )
    
    # 文献信息
    literature_id = Column(
        Integer,
        ForeignKey("literature.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="文献ID（关联模块1的literature表）"
    )
    pmid = Column(String(20), nullable=False, index=True, comment="PubMed ID")
    title = Column(String(500), nullable=False, comment="文献标题")
    
    # 时间戳
    added_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="添加时间"
    )
    
    # 唯一约束：同一订阅不重复添加同一文献
    __table_args__ = (
        UniqueConstraint("subscription_id", "literature_id", name="uq_subscription_literature"),
        Index("idx_pool_article_subscription_id", "subscription_id"),
        Index("idx_pool_article_pmid", "pmid"),
        Index("idx_pool_article_added_at", "added_at"),
    )
    
    def __repr__(self):
        return f"<PoolArticle(id={self.id}, subscription_id={self.subscription_id}, pmid={self.pmid})>"
