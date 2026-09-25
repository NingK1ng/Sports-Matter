"""
CandidateArticle模型 - 统一的候选文献DTO
任务1.3: 统一数据模型
"""
from pydantic import BaseModel, Field
from typing import Literal, Optional


class CandidateArticle(BaseModel):
    """统一的候选文献模型（本地检索+Agent检索）"""

    pmid: Optional[str] = Field(None, description="PubMed ID（可选，journal文章可能没有）")
    doi: Optional[str] = Field(None, description="DOI（备用标识符）")
    title: str = Field(..., description="文献标题")
    abstract: str = Field("", description="摘要（可能为空）")
    url: str = Field(..., description="文献URL（PubMed或DOI链接）")
    source: Literal["literature", "journals", "pubmed_agent"] = Field(
        ...,
        description="数据来源: literature(模块1) | journals(模块2) | pubmed_agent(Agent在线检索)"
    )
    journal_name: Optional[str] = Field(None, description="期刊名称")
    publication_year: Optional[int] = Field(None, description="发表年份")
    authors: Optional[str] = Field(None, description="作者列表（简化字符串）")
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "pmid": "38123456",
                "title": "Effects of high-intensity interval training on VO2max",
                "abstract": "Background: HIIT has been shown to...",
                "url": "https://pubmed.ncbi.nlm.nih.gov/38123456/",
                "source": "literature",
                "journal_name": "Sports Medicine",
                "publication_year": 2024,
                "authors": "Smith J, et al."
            }
        }

