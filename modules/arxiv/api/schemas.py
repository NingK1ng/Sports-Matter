"""
arXiv API数据模式
"""
from datetime import date
from typing import Optional, List, Dict
from pydantic import BaseModel, Field


class ArxivArticleResponse(BaseModel):
    """arXiv文章响应"""

    id: int
    arxiv_id: str
    version: int
    source: str
    title: str
    title_zh: Optional[str] = None
    abstract: Optional[str] = None
    abstract_zh: Optional[str] = None
    primary_category: Optional[str] = None
    categories: Optional[List[str]] = None
    sport_category: Optional[str] = None
    sport_relevance: Optional[float] = None
    authors: Optional[List[Dict]] = None
    published_date: Optional[date] = None
    updated_date: Optional[date] = None
    submitted_date: Optional[date] = None
    pdf_url: Optional[str] = None
    abs_url: Optional[str] = None

    class Config:
        from_attributes = True


class ArxivArticleListResponse(BaseModel):
    """文章列表响应"""

    total: int = Field(..., description="总文章数")
    page: int = Field(..., description="当前页码")
    per_page: int = Field(..., description="每页数量")
    pages: int = Field(..., description="总页数")
    items: List[ArxivArticleResponse] = Field(..., description="文章列表")


class ArxivCategoryResponse(BaseModel):
    """分类响应"""

    category_key: str
    display_name: str
    description: Optional[str] = None
    doc_count: int = 0

    class Config:
        from_attributes = True


class ArxivStatsResponse(BaseModel):
    """统计响应"""

    total_articles: int = Field(..., description="总文章数")
    category_counts: Dict[str, int] = Field(..., description="各分类文章数")
