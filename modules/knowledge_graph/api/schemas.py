"""
知识图谱API数据模型
"""
from datetime import date
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class KeywordTerm(BaseModel):
    """关键词"""
    term: str = Field(..., description="关键词")
    score: float = Field(..., description="重要性分数", ge=0, le=1)


class TopPaper(BaseModel):
    """Top论文"""
    pmid: str = Field(..., description="PubMed ID")
    title: str = Field(..., description="文献标题")
    abstract: Optional[str] = Field(None, description="摘要")
    score: float = Field(..., description="相关性分数", ge=0, le=1)
    pub_date: Optional[str] = Field(None, description="发表日期")


class CommunityMetrics(BaseModel):
    """社区指标"""
    modularity: float = Field(..., description="模块度")
    density: float = Field(..., description="密度")
    coverage: float = Field(..., description="覆盖率")
    keywords_coverage: float = Field(..., description="关键词覆盖率")
    detector: str = Field(..., description="检测器: fasttree|louvain|fallback")
    degraded: bool = Field(..., description="是否降级")


class SnapshotMeta(BaseModel):
    """快照元数据"""
    snapshot_id: str = Field(..., description="快照ID")
    source: str = Field(..., description="数据源")
    window: str = Field(..., description="时间窗口")
    as_of: str = Field(..., description="快照日期")
    meta: Dict[str, Any] = Field(..., description="图谱统计")


class CommunitySummary(BaseModel):
    """社区摘要（用于列表）"""
    community_id: str = Field(..., description="社区ID")
    size: int = Field(..., description="社区大小")
    activity: float = Field(..., description="活跃度")
    representative_terms: List[KeywordTerm] = Field(default=[], description="代表性关键词（≤3）")
    top_papers: List[TopPaper] = Field(default=[], description="Top论文（≤3）")
    llm_label: Optional[str] = Field(default=None, description="LLM聚类生成的主学术标签")
    llm_candidates: List[str] = Field(default_factory=list, description="LLM聚类生成的候选同义/近义术语")
    summary: Optional[str] = Field(default=None, description="社区摘要（精简版，随快照更新）")


class CommunityListResponse(BaseModel):
    """社区列表响应"""
    items: List[CommunitySummary] = Field(..., description="社区列表")
    snapshot: SnapshotMeta = Field(..., description="快照信息")
    total: int = Field(..., description="社区总数")


class CommunityDetail(BaseModel):
    """社区详情"""
    community_id: str = Field(..., description="社区ID")
    size: int = Field(..., description="社区大小")
    activity: float = Field(..., description="活跃度")
    representative_terms: List[KeywordTerm] = Field(..., description="代表性关键词（≤10）")
    top_papers: List[TopPaper] = Field(..., description="Top10论文")
    summary: Optional[str] = Field(None, description="LLM生成的摘要")
    metrics: CommunityMetrics = Field(..., description="社区指标")
    snapshot: SnapshotMeta = Field(..., description="快照信息")
    graph_data: Optional[Dict[str, Any]] = Field(None, description="子图数据（可选）")


class WiWRequest(BaseModel):
    """WiW分析请求"""
    lang: str = Field(default="zh", description="语言: zh|en")
    force_regenerate: bool = Field(default=False, description="强制重新生成（忽略缓存）")


class WiWCitation(BaseModel):
    """WiW 引用信息"""
    index: int = Field(..., description="文献编号（从1开始）")
    pmid: Optional[str] = Field(default=None, description="PubMed ID")
    doi: Optional[str] = Field(default=None, description="DOI")
    url: Optional[str] = Field(default=None, description="引用链接（PubMed/DOI等）")


class WiWResponse(BaseModel):
    """WiW分析响应"""
    community_id: str = Field(..., description="社区ID")
    wiw_analysis: str = Field(..., description="WiW分析结果")
    generated_at: str = Field(..., description="生成时间")
    citations: List[WiWCitation] = Field(default_factory=list, description="引用映射（用于前端生成超链接）")
