"""
API数据模型（Pydantic schemas）
"""
from datetime import date, datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class CategoryResponse(BaseModel):
    """学科分类响应"""
    id: int
    category_key: str
    display_name: str
    description: Optional[str]
    pubmed_query: str
    doc_count: int
    display_order: Optional[int]
    is_enabled: bool
    
    class Config:
        from_attributes = True


class LiteratureResponse(BaseModel):
    """文献响应"""
    id: int
    pmid: str
    doi: Optional[str]
    title: str
    title_zh: Optional[str] = Field(default=None, description="中文标题（DeepSeek翻译）")
    abstract: Optional[str]
    authors: List[str]
    publication_date: Optional[date]
    journal_name: Optional[str]
    journal_issn: Optional[str]
    journal_if_5y: Optional[float]
    journal_citescore: Optional[float]
    journal_zone: Optional[str]
    subject_categories: List[str]
    literature_types: List[str]
    extra_metadata: Optional[Dict[str, Any]]
    # 相关度分数（仅在 sort_by=relevance 且提供 keywords 时返回）
    rank: Optional[float] = Field(default=None)

    class Config:
        from_attributes = True


class LiteratureListResponse(BaseModel):
    """文献列表响应（分页）"""
    total: int
    page: int
    per_page: int
    pages: int
    items: List[LiteratureResponse]


class JournalResponse(BaseModel):
    """期刊响应"""
    id: int
    issn: str
    nlm_abbr: Optional[str]
    full_name: str
    if_5y: Optional[float]
    citescore: Optional[float]
    h_index: Optional[int]
    composite_score: Optional[float]
    cas_zone: Optional[str]
    is_top_journal: bool
    is_blacklisted: bool
    
    class Config:
        from_attributes = True


class QueryResponse(BaseModel):
    """检索式响应"""
    category_key: str
    display_name: str
    pubmed_query: str


class CrawlStatsResponse(BaseModel):
    """爬取统计响应"""
    total_literature: int
    by_category: Dict[str, int]
    by_type: Dict[str, int]
    last_crawl: Optional[datetime]
