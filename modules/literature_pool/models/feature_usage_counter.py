"""
FeatureUsageCounter Model - 功能试用次数计数器

用于实现「每周 N 次」的统一试用限制（按用户计数）。
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Date,
    Integer,
    String,
    TIMESTAMP,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)

from models.base import Base


class FeatureUsageCounter(Base):
    """功能试用次数计数器（按周）"""

    __tablename__ = "feature_usage_counters"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID",
    )

    feature_key = Column(String(64), nullable=False, comment="功能标识")
    week_start = Column(Date, nullable=False, comment="周起始日期（周一）")
    count = Column(Integer, nullable=False, server_default=text("0"), comment="本周已使用次数")

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
        UniqueConstraint(
            "user_id",
            "feature_key",
            "week_start",
            name="uq_feature_usage_user_feature_week",
        ),
        Index(
            "idx_feature_usage_feature_week",
            "feature_key",
            "week_start",
        ),
        Index(
            "idx_feature_usage_user_week",
            "user_id",
            "week_start",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<FeatureUsageCounter(id={self.id}, user_id={self.user_id}, "
            f"feature_key={self.feature_key}, week_start={self.week_start}, count={self.count})>"
        )

