"""
文献流模块数据库模型
基于 openspec/changes/add-literature-stream/DATABASE_SCHEMA.md
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
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

# 使用项目统一的Base，而不是创建独立的Base
from models.base import Base


class Literature(Base):
    """文献主表 - 存储所有爬取的文献元数据"""
    
    __tablename__ = "literature"
    
    # 主键和唯一标识
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    pmid = Column(String(20), nullable=False, unique=True, index=True, comment="PubMed ID")
    doi = Column(String(100), nullable=True, comment="Digital Object Identifier")
    
    # 基础元数据
    title = Column(Text, nullable=False, comment="文献标题")
    title_zh = Column(Text, nullable=True, comment="中文标题（DeepSeek翻译）")
    abstract = Column(Text, nullable=True, comment="摘要")
    abstract_zh = Column(Text, nullable=True, comment="中文摘要（DeepSeek翻译）")
    authors = Column(ARRAY(Text), nullable=True, comment="作者数组")
    publication_date = Column(Date, nullable=True, comment="发表日期（解析失败时为NULL）")
    
    # 期刊信息（冗余存储，避免JOIN）
    journal_name = Column(String(200), nullable=True, comment="期刊名称")
    journal_issn = Column(String(20), nullable=True, comment="期刊ISSN - 用于匹配")
    journal_nlm_abbr = Column(String(100), nullable=True, comment="NLM缩写 - 备用匹配")
    journal_if_5y = Column(Numeric(5, 2), nullable=True, comment="5年影响因子")
    journal_citescore = Column(Numeric(5, 2), nullable=True, comment="CiteScore备用指标")
    journal_zone = Column(String(10), nullable=True, comment="中科院分区")
    
    # 分类标签（支持多标签）
    subject_categories = Column(
        ARRAY(String(50)),
        nullable=True,
        comment="学科类别数组 - 如 ['sports_medicine', 'training_science']"
    )
    literature_types = Column(
        ARRAY(String(50)),
        nullable=True,
        comment="文献类型数组 - 如 ['meta_analysis', 'original_human']"
    )
    
    # 完整元数据（JSONB存储灵活字段）
    extra_metadata = Column(
        JSONB,
        nullable=True,
        comment="额外元数据: mesh_terms, keywords, funding, pubmed_url, pmc_id等"
    )
    
    # Embedding向量（用于知识图谱，按需启用）
    if os.getenv("KG_ENABLE_EMBEDDINGS", "0").lower() in ("1", "true", "yes"):
        embedding = Column(
            "embedding",
            Text,  # 与DB的pgvector类型在ORM层不强制匹配；此处仅为占位，避免编译错误
            nullable=True,
            comment="语义向量(384维,all-MiniLM-L6-v2)"
        )
    
    # 关键词（用于知识图谱）
    keywords_json = Column(
        JSONB,
        nullable=True,
        comment="LLM抽取的关键词: [{term: str, source: abstract|title, score: float}]"
    )
    
    # 爬取元信息
    crawled_at = Column(TIMESTAMP, nullable=False, server_default=text("NOW()"), comment="爬取时间")
    updated_at = Column(
        TIMESTAMP,
        nullable=False,
        server_default=text("NOW()"),
        onupdate=datetime.utcnow,
        comment="更新时间"
    )
    is_deleted = Column(Boolean, nullable=False, server_default=text("FALSE"), comment="软删除标记")
    
    # 全文检索向量（预计算）
    searchable_text = Column(TSVECTOR, nullable=True, comment="全文检索向量(title+abstract)")
    # 对齐模块2：拆分标题/摘要向量
    title_vector = Column(TSVECTOR, nullable=True, comment="标题向量（unaccent, english）")
    abstract_vector = Column(TSVECTOR, nullable=True, comment="摘要向量（unaccent, english）")
    
    # 审计字段
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("NOW()"), comment="创建时间")
    
    # 索引定义
    __table_args__ = (
        # GIN索引 - 数组字段
        Index("idx_lit_subject_cats", "subject_categories", postgresql_using="gin"),
        Index("idx_lit_lit_types", "literature_types", postgresql_using="gin"),
        # Btree索引 - 排序字段
        Index("idx_lit_pub_date", "publication_date", postgresql_ops={"publication_date": "DESC"}),
        # Partial index - 期刊过滤
        Index(
            "idx_lit_journal_issn",
            "journal_issn",
            postgresql_where=text("journal_issn IS NOT NULL")
        ),
        # GIN索引 - 全文检索
        Index("idx_lit_searchable", "searchable_text", postgresql_using="gin"),
        Index("idx_lit_title_fts", "title_vector", postgresql_using="gin"),
        Index("idx_lit_abstract_fts", "abstract_vector", postgresql_using="gin"),
        # GIN索引 - JSONB元数据
        Index("idx_lit_extra_metadata", "extra_metadata", postgresql_using="gin", postgresql_ops={"extra_metadata": "jsonb_path_ops"}),
        {"comment": "文献主表"},
    )


class JournalMetadata(Base):
    """期刊元数据表 - 存储113本期刊的静态元数据"""
    
    __tablename__ = "journal_metadata"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    issn = Column(String(20), nullable=False, unique=True, comment="期刊ISSN - 主键")
    nlm_abbr = Column(String(100), nullable=True, comment="NLM缩写 - 备用匹配")
    full_name = Column(String(300), nullable=False, comment="期刊全名")
    
    # 评价指标
    if_5y = Column(Numeric(5, 2), nullable=True, comment="5年影响因子")
    citescore = Column(Numeric(5, 2), nullable=True, comment="CiteScore")
    h_index = Column(Integer, nullable=True, comment="h指数")
    composite_score = Column(Numeric(3, 1), nullable=True, comment="综合评分")
    cas_zone = Column(String(10), nullable=True, comment="中科院分区")
    
    # 分类标识
    is_top_journal = Column(Boolean, nullable=False, server_default=text("FALSE"), comment="是否5本顶刊")
    is_blacklisted = Column(Boolean, nullable=False, server_default=text("FALSE"), comment="是否黑名单")
    
    # 额外元数据
    extra_metadata = Column(
        JSONB,
        nullable=True,
        comment="额外信息: publisher, subject_areas, open_access等"
    )
    
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("NOW()"))
    updated_at = Column(
        TIMESTAMP,
        nullable=False,
        server_default=text("NOW()"),
        onupdate=datetime.utcnow
    )
    
    # 索引
    __table_args__ = (
        Index("idx_journal_issn_unique", "issn", unique=True),
        Index("idx_journal_nlm_abbr", "nlm_abbr"),
        Index(
            "idx_journal_top",
            "is_top_journal",
            postgresql_where=text("is_top_journal = TRUE")
        ),
        Index(
            "idx_journal_blacklist",
            "is_blacklisted",
            postgresql_where=text("is_blacklisted = TRUE")
        ),
        {"comment": "期刊元数据表（113本）"},
    )


class SubjectCategoryConfig(Base):
    """学科分类配置表 - 存储8大学科类的检索式和元数据"""
    
    __tablename__ = "subject_category_config"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    category_key = Column(String(50), nullable=False, unique=True, comment="分类键 - 如 'sports_education'")
    display_name = Column(String(100), nullable=False, comment="显示名称 - 如 '体育教育'")
    description = Column(Text, nullable=True, comment="分类描述")
    
    # PubMed检索式
    pubmed_query = Column(Text, nullable=False, comment="完整的MeSH检索式")
    
    # 统计信息（定期更新）
    doc_count = Column(Integer, nullable=False, server_default=text("0"), comment="当前文献数量")
    last_updated = Column(TIMESTAMP, nullable=True, comment="最后统计更新时间")
    
    # 排序和启用状态
    display_order = Column(Integer, nullable=True, comment="显示顺序")
    is_enabled = Column(Boolean, nullable=False, server_default=text("TRUE"), comment="是否启用")
    
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("NOW()"))
    
    __table_args__ = (
        Index("idx_category_key", "category_key", unique=True),
        Index("idx_category_enabled", "is_enabled"),
        {"comment": "学科分类配置表（8大类）"},
    )


class CrawlTaskLog(Base):
    """爬取任务日志表 - 记录爬取任务执行历史"""
    
    __tablename__ = "crawl_task_log"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_type = Column(
        String(50),
        nullable=False,
        comment="任务类型: 'incremental_daily' / 'warm_start' / 'manual'"
    )
    category_key = Column(String(50), nullable=True, comment="针对哪个学科类（null表示全部）")
    
    # 执行参数（关键：记录时区、窗口和断点）
    query_params = Column(
        JSONB,
        nullable=False,
        comment="""
        执行参数JSON: {
            "window_start_utc": "2023-12-31T17:45:00Z",
            "window_end_utc": "2024-01-01T18:00:00Z",
            "window_start_utc8": "2024-01-01T01:45:00+08",
            "window_end_utc8": "2024-01-02T02:00:00+08",
            "overlap_minutes": 15,
            "actual_edat_query": "[2023/12/31 17:45:00:2024/01/01 18:00:00]",
            "retstart": 0,
            "retmax": 500,
            "total_batches": 3
        }
        """
    )
    
    # 断点续跑参数（失败重试时使用）
    last_successful_edat = Column(
        TIMESTAMP,
        nullable=True,
        comment="上次成功爬取的最后一篇文献EDAT（UTC时区）"
    )
    retry_start_position = Column(
        Integer,
        nullable=True,
        comment="断点位置（retstart参数）"
    )
    
    # 执行结果
    status = Column(
        String(20),
        nullable=False,
        comment="状态: 'running' / 'success' / 'failed'"
    )
    total_fetched = Column(Integer, nullable=False, server_default=text("0"), comment="总获取数")
    new_inserted = Column(Integer, nullable=False, server_default=text("0"), comment="新增数")
    duplicates_skipped = Column(Integer, nullable=False, server_default=text("0"), comment="跳过数")
    error_message = Column(Text, nullable=True, comment="错误信息（如果失败）")
    
    # 时间记录（全部使用UTC时区）
    started_at = Column(TIMESTAMP, nullable=False, comment="开始时间（UTC）")
    finished_at = Column(TIMESTAMP, nullable=True, comment="完成时间（UTC）")
    duration_seconds = Column(Integer, nullable=True, comment="执行时长（秒）")
    
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("NOW()"))
    
    # 索引
    __table_args__ = (
        Index("idx_crawl_status", "status", "started_at", postgresql_ops={"started_at": "DESC"}),
        Index("idx_crawl_category", "category_key", "started_at", postgresql_ops={"started_at": "DESC"}),
        Index(
            "idx_crawl_last_success",
            "last_successful_edat",
            postgresql_ops={"last_successful_edat": "DESC"},
            postgresql_where=text("status = 'success'")
        ),
        CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="check_status_valid"
        ),
        {"comment": "爬取任务日志表"},
    )
