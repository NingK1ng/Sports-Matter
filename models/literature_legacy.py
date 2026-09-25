"""
文献数据模型

存储PubMed等来源的文献元数据
"""

from typing import Optional
from sqlalchemy import String, Text, Integer, Date, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class Literature(Base, TimestampMixin):
    """文献模型"""

    __tablename__ = "literature"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 外部标识符
    pmid: Mapped[Optional[str]] = mapped_column(String(20), unique=True, index=True)
    doi: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True)

    # 基本信息
    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[Optional[str]] = mapped_column(Text)
    authors: Mapped[Optional[list]] = mapped_column(JSON)  # JSON数组
    keywords: Mapped[Optional[list]] = mapped_column(JSON)

    # 出版信息
    journal: Mapped[Optional[str]] = mapped_column(String(500))
    journal_issn: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    pub_date: Mapped[Optional[str]] = mapped_column(String(50))
    pub_year: Mapped[Optional[int]] = mapped_column(Integer, index=True)

    # 学术指标
    cited_by_count: Mapped[int] = mapped_column(Integer, default=0)
    citation_updated_at: Mapped[Optional[str]] = mapped_column(String(50))

    # 分类与标签
    categories: Mapped[Optional[list]] = mapped_column(JSON)
    mesh_terms: Mapped[Optional[list]] = mapped_column(JSON)

    # 全文链接
    full_text_url: Mapped[Optional[str]] = mapped_column(String(1000))
    pdf_url: Mapped[Optional[str]] = mapped_column(String(1000))

    # 索引
    __table_args__ = (
        Index("idx_pub_year", "pub_year"),
        Index("idx_journal_issn", "journal_issn"),
        Index("idx_pmid", "pmid"),
        Index("idx_doi", "doi"),
    )

    def __repr__(self):
        return f"<Literature(id={self.id}, pmid={self.pmid}, title={self.title[:50]}...)>"
