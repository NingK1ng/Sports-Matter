"""
Feed API Schemas
"""
from typing import List, Dict, Any, Optional
from datetime import date
from pydantic import BaseModel


class WiWCardResponse(BaseModel):
    """WiW卡片响应"""
    id: int
    wiw_result_id: int
    source_pmid: str
    track: str
    generated_at: str
    expires_at: str
    is_expired: bool
    card: Dict[str, Any]  # 完整的card JSON


class ArticleResponse(BaseModel):
    """文献响应（复用模块2的ArticleResponse）"""
    id: int
    doi: str
    title: str
    abstract: Optional[str] = None
    abstract_source: str = "unknown"
    authors: List[Dict[str, Any]] = []
    published_at_precise: str
    publication_date: str  # 改为字符串，因为从缓存读取时已是字符串
    journal_issn: str
    journal_name: Optional[str] = None
    category: str = "unknown"
    cited_by_count: Optional[int] = None
    cited_by_percentile_year: Optional[float] = None
    labels: List[str] = []
    
    class Config:
        from_attributes = True


class FeedResponse(BaseModel):
    """Feed流响应"""
    stream_cards: List[WiWCardResponse]  # 模块1卡片
    journals_cards: List[WiWCardResponse]  # 模块2卡片
    journals_articles: List[ArticleResponse]  # 模块2文献列表
    total_stream_cards: int
    total_journals_cards: int
    total_journals_articles: int
