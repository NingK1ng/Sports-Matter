"""
顶刊追踪模块数据库模型
基于 openspec/changes/add-journals-tracking/tasks.md 任务1.2-1.4
"""
from datetime import datetime
from typing import List, Optional
import os

from sqlalchemy import (
    Boolean,
    Column,
    BigInteger,
    Integer,
    String,
    Text,
    Date,
    TIMESTAMP,
    Numeric,
    Index,
    text,
    UniqueConstraint,
    CheckConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR

from models.base import Base


class JournalArticle(Base):
    """期刊文章主表 - 存储所有追踪期刊的文章"""
    
    __tablename__ = "journal_articles"
    
    # 主键和唯一标识
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    doi = Column(String(100), nullable=False, unique=True, index=True, comment="DOI（唯一标识，归一化：小写、去空格）")
    
    # 基础元数据
    title = Column(Text, nullable=False, comment="文章标题")
    title_zh = Column(Text, nullable=True, comment="中文标题（DeepSeek翻译）")
    abstract = Column(Text, nullable=True, comment="摘要（可能为空）")
    abstract_zh = Column(Text, nullable=True, comment="中文摘要（DeepSeek翻译）")
    abstract_source = Column(String(20), nullable=False, server_default=text("'crossref'"), comment="摘要来源：crossref|pubmed|openalex|publisher|none")
    authors = Column(JSONB, nullable=True, comment="作者数组（JSONB格式）")
    
    # 时间字段（新增，任务1.2）
    published_at_precise = Column(TIMESTAMP(timezone=True), nullable=False, comment="发表时间（精确到秒，Crossref优先级：published-online → published-print → issued → created）")
    publication_date = Column(Date, nullable=False, comment="发表日期（由published_at_precise派生，用于聚合/筛选）")
    indexed_at = Column(TIMESTAMP(timezone=True), nullable=True, comment="Crossref收录时间（用于增量滑窗）")
    
    # 期刊信息
    pmid = Column(String(20), nullable=True, comment="PubMed PMID")
    journal_issn = Column(String(20), nullable=False, comment="期刊ISSN-L（主键）")
    journal_name = Column(String(200), nullable=True, comment="期刊名称")
    category = Column(String(50), nullable=False, comment="期刊分类：sports_science|cns")
    
    # OpenAlex被引数据
    openalex_id = Column(String(100), nullable=True, comment="OpenAlex作品ID")
    cited_by_count = Column(Integer, nullable=True, comment="被引次数")
    cited_by_percentile_year = Column(Numeric(5, 2), nullable=True, comment="年度被引分位数")
    
    # 标签字段（两阶段标签系统）
    labels = Column(ARRAY(String(20)), nullable=True, comment="标签数组：new|recent|trending|hot|classic")
    
    # 爬取元信息
    first_seen_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"), comment="首次爬取时间")
    last_citation_update_at = Column(TIMESTAMP(timezone=True), nullable=True, comment="最后被引更新时间")
    
    # 全文检索向量（任务1.2）
    title_vector = Column(TSVECTOR, nullable=True, comment="标题搜索向量")
    abstract_vector = Column(TSVECTOR, nullable=True, comment="摘要搜索向量")
    
    # Embedding向量（按需启用，未启用时不声明列以避免编译错误）
    if os.getenv("KG_ENABLE_EMBEDDINGS", "0").lower() in ("1", "true", "yes"):
        embedding = Column(
            "embedding",
            Text,  # 与DB的pgvector类型在ORM层不强制匹配；此处仅为占位
            nullable=True,
            comment="语义向量(384维,all-MiniLM-L6-v2)"
        )
    keywords_json = Column(
        JSONB,
        nullable=True,
        comment="LLM抽取的关键词: [{term: str, source: abstract|title, score: float}]"
    )
    extra_metadata = Column(JSONB, nullable=True, comment="额外元数据: mesh_terms, keywords等")
    
    # 审计字段
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"), comment="创建时间")
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"), comment="更新时间")
    
    # 索引定义（任务1.4）
    __table_args__ = (
        # UNIQUE约束
        UniqueConstraint("doi", name="uq_journal_articles_doi"),
        # PMID唯一（允许NULL）
        UniqueConstraint("pmid", name="uq_journal_articles_pmid"),
        
        # Btree索引 - 排序字段
        Index("idx_articles_pub_date", "publication_date", postgresql_ops={"publication_date": "DESC"}),
        Index("idx_articles_category_date", "category", "publication_date", postgresql_ops={"publication_date": "DESC"}),
        Index("idx_articles_issn_date", "journal_issn", "publication_date", postgresql_ops={"publication_date": "DESC"}),
        # PMID索引（便于定位）
        Index("idx_articles_pmid", "pmid"),
        
        # GIN索引 - 数组字段
        Index("idx_articles_labels", "labels", postgresql_using="gin"),
        
        # GIN索引 - 全文检索（任务1.4）
        Index("idx_articles_title_fts", "title_vector", postgresql_using="gin"),
        Index("idx_articles_abstract_fts", "abstract_vector", postgresql_using="gin"),
        
        # Btree索引 - 被引数排序
        Index("idx_articles_citations", "cited_by_count", postgresql_ops={"cited_by_count": "DESC NULLS LAST"}),
        
        {"comment": "期刊文章主表"},
    )


class JournalMetadata(Base):
    """期刊元数据表（顶刊追踪） - 存储13本期刊的静态元数据和ISSN-L映射"""

    __tablename__ = "journal_metadata_tracked"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    issn_l = Column(String(20), nullable=False, unique=True, comment="ISSN-L（主键）")
    issn_print = Column(String(20), nullable=True, comment="Print ISSN")
    issn_electronic = Column(String(20), nullable=True, comment="Electronic ISSN")
    
    full_name = Column(String(300), nullable=False, comment="期刊全名")
    short_name = Column(String(100), nullable=True, comment="期刊简称")
    display_name = Column(String(100), nullable=False, comment="显示名称")
    
    # 分类和评价
    category = Column(String(50), nullable=False, comment="期刊分类：sports_science|cns")
    estimated_if = Column(Numeric(5, 2), nullable=True, comment="估计影响因子")
    publisher = Column(String(200), nullable=True, comment="出版商")
    website_url = Column(String(500), nullable=True, comment="期刊网站")
    
    # 爬取状态
    last_crawled_until = Column(TIMESTAMP(timezone=True), nullable=True, comment="最后爬取截止时间")
    article_count = Column(Integer, nullable=False, server_default=text("0"), comment="文章总数")
    
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
    
    # 索引
    __table_args__ = (
        Index("idx_journal_tracked_issn_l", "issn_l", unique=True),
        Index("idx_journal_tracked_category", "category"),
        {"comment": "期刊元数据表（13本，顶刊追踪）"},
    )


class JournalCrawlState(Base):
    """期刊爬取状态表 - 支持断点续传（任务2.4）"""
    
    __tablename__ = "journal_crawl_state"
    
    issn_l = Column(String(20), primary_key=True, comment="期刊ISSN-L")
    last_crawled_until = Column(TIMESTAMP(timezone=True), nullable=True, comment="最后成功爬取的截止时间（UTC）")
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"), comment="更新时间")
    
    __table_args__ = (
        {"comment": "期刊爬取状态表（断点续传）"},
    )


class CrawlTaskLog(Base):
    """爬取任务日志表 - 记录爬取任务执行历史（任务2.4）"""
    
    __tablename__ = "crawl_task_log_journals"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_type = Column(String(50), nullable=False, comment="任务类型：incremental|cold_start|citation_update")
    issn_l = Column(String(20), nullable=True, comment="期刊ISSN-L（null表示全部）")
    
    # 执行参数
    window_from = Column(TIMESTAMP(timezone=True), nullable=True, comment="时间窗口起始（UTC）")
    window_until = Column(TIMESTAMP(timezone=True), nullable=True, comment="时间窗口结束（UTC）")
    
    # 执行结果
    status = Column(String(20), nullable=False, comment="状态：running|success|failed")
    total_fetched = Column(Integer, nullable=False, server_default=text("0"), comment="总获取数")
    new_inserted = Column(Integer, nullable=False, server_default=text("0"), comment="新增数")
    updated_count = Column(Integer, nullable=False, server_default=text("0"), comment="更新数")
    retries = Column(Integer, nullable=False, server_default=text("0"), comment="重试次数")
    error_message = Column(Text, nullable=True, comment="错误信息")
    
    # 时间记录
    started_at = Column(TIMESTAMP(timezone=True), nullable=False, comment="开始时间（UTC）")
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True, comment="完成时间（UTC）")
    
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("NOW()"))
    
    # 索引
    __table_args__ = (
        Index("idx_crawl_log_status", "status", "started_at", postgresql_ops={"started_at": "DESC"}),
        Index("idx_crawl_log_issn", "issn_l", "started_at", postgresql_ops={"started_at": "DESC"}),
        CheckConstraint("status IN ('running', 'success', 'failed')", name="check_status_valid_journals"),
        {"comment": "爬取任务日志表（顶刊追踪）"},
    )
