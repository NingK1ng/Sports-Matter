"""
期刊数据模型

存储期刊元数据和影响因子
"""

from typing import Optional
from sqlalchemy import String, Float, Integer, Boolean, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class Journal(Base, TimestampMixin):
    """期刊模型"""

    __tablename__ = "journal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 标识符
    issn: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    eissn: Mapped[Optional[str]] = mapped_column(String(20))

    # 基本信息
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    abbreviation: Mapped[Optional[str]] = mapped_column(String(200))
    publisher: Mapped[Optional[str]] = mapped_column(String(500))

    # 影响因子
    impact_factor: Mapped[Optional[float]] = mapped_column(Float)
    impact_factor_year: Mapped[Optional[int]] = mapped_column(Integer)

    # 学科分类
    categories: Mapped[Optional[list]] = mapped_column(JSON)
    disciplines: Mapped[Optional[list]] = mapped_column(JSON)

    # 标签
    is_top_journal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_tracked: Mapped[bool] = mapped_column(Boolean, default=False)

    # 其他信息
    country: Mapped[Optional[str]] = mapped_column(String(100))
    language: Mapped[Optional[str]] = mapped_column(String(50))
    website: Mapped[Optional[str]] = mapped_column(String(500))

    # 索引
    __table_args__ = (
        Index("idx_issn", "issn"),
        Index("idx_is_top_journal", "is_top_journal"),
    )

    def __repr__(self):
        return f"<Journal(id={self.id}, issn={self.issn}, title={self.title})>"
