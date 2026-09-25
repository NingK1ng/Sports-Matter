"""
API响应模型
"""
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class JournalResponse(BaseModel):
    """期刊信息响应"""
    issn_l: str
    issn_print: Optional[str]
    issn_electronic: Optional[str]
    full_name: str
    short_name: Optional[str]
    display_name: str
    category: str
    estimated_if: Optional[float]
    publisher: Optional[str]
    website_url: Optional[str]
    article_count: int
    
    class Config:
        from_attributes = True


class ArticleResponse(BaseModel):
    """文章信息响应"""
    id: int
    doi: str
    title: str
    title_zh: Optional[str] = Field(default=None, description="中文标题（DeepSeek翻译）")
    abstract: Optional[str]
    abstract_source: str
    authors: Optional[List[Dict[str, Any]]]
    published_at_precise: datetime
    publication_date: date
    journal_issn: str
    journal_name: Optional[str]
    category: str
    cited_by_count: Optional[int]
    cited_by_percentile_year: Optional[float]
    labels: Optional[List[str]]
    rank: Optional[float] = None  # 搜索相关度评分（可选）

    class Config:
        from_attributes = True


class ArticleListResponse(BaseModel):
    """文章列表响应"""
    total: int
    page: int
    per_page: int
    pages: int
    items: List[ArticleResponse]


class StatsResponse(BaseModel):
    """统计信息响应"""
    total_articles: int
    by_category: Dict[str, int]
    by_journal: Dict[str, int]
    last_crawl: Optional[datetime]
