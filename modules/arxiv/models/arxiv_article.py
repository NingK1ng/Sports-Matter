"""
arXiv文章模型
"""
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import (
    Column,
    BigInteger,
    String,
    Text,
    Date,
    DateTime,
    Boolean,
    Integer,
    DECIMAL,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from models.base import Base


class ArxivArticle(Base):
    """arXiv文章表"""

    __tablename__ = "arxiv_articles"

    # 主键和唯一标识
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    arxiv_id = Column(String(20), nullable=False, unique=True, comment="arXiv ID（去版本号）")
    version = Column(Integer, default=1, comment="版本号")
    source = Column(String(20), nullable=False, default="arxiv", comment="来源：arxiv/biorxiv")

    # 基础元数据
    title = Column(Text, nullable=False, comment="标题")
    title_zh = Column(Text, comment="中文标题")
    abstract = Column(Text, comment="摘要")
    abstract_zh = Column(Text, comment="中文摘要")

    # arXiv原始分类
    primary_category = Column(String(50), comment="主分类")
    categories = Column(JSONB, comment="所有分类数组")

    # LLM运动科学分类（4大类）
    sport_category = Column(String(50), comment="运动科学分类：technology/training/science/medicine")
    sport_relevance = Column(DECIMAL(3, 2), comment="运动科学相关度0.00-1.00")

    # 作者与时间
    authors = Column(JSONB, comment="作者列表")
    published_date = Column(Date, comment="首次发布日期")
    updated_date = Column(Date, comment="最后更新日期")
    submitted_date = Column(Date, comment="提交日期")

    # 链接
    pdf_url = Column(String(500), comment="PDF下载地址")
    abs_url = Column(String(500), comment="摘要页地址")

    # 全文检索向量
    title_vector = Column(TSVECTOR, comment="标题向量")
    abstract_vector = Column(TSVECTOR, comment="摘要向量")

    # 审计
    crawled_at = Column(DateTime, default=datetime.utcnow, comment="爬取时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
    is_deleted = Column(Boolean, default=False, comment="软删除标记")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


# 索引
Index("idx_arxiv_id", ArxivArticle.arxiv_id, unique=True)
Index("idx_arxiv_sport_category", ArxivArticle.sport_category, postgresql_where=ArxivArticle.sport_category.isnot(None))
Index("idx_arxiv_submitted_date", ArxivArticle.submitted_date.desc())
Index("idx_arxiv_title_fts", ArxivArticle.title_vector, postgresql_using="gin")
Index("idx_arxiv_abstract_fts", ArxivArticle.abstract_vector, postgresql_using="gin")
Index("idx_arxiv_source", ArxivArticle.source)
Index("idx_arxiv_categories_gin", ArxivArticle.categories, postgresql_using="gin")
