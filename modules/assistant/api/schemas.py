"""
Assistant API Schemas
"""
from pydantic import BaseModel, Field, model_validator
from typing import List, Dict, Optional


class AssistantChatRequest(BaseModel):
    """AI助手聊天请求"""
    query: str = Field(..., description="用户查询", min_length=1, max_length=500)
    sports_gate: bool = Field(False, description="Sports Gate开关（仅Agent模式生效）")
    use_agent: bool = Field(False, description="是否使用Agent模式")
    # 兼容旧字段名 agent_mode（如果传入则映射到 use_agent）
    agent_mode: Optional[bool] = Field(None, description="兼容字段，等同use_agent")
    top_k: int = Field(10, description="召回文献数量", ge=1, le=50)
    lang: str = Field("zh", description="语言: zh|en", pattern="^(zh|en)$")
    model: str = Field(
        "deepseek-v4-flash",
        description="LLM模型: deepseek-v4-flash（兼容旧deepseek-chat|deepseek-reasoner入参）",
        pattern="^(deepseek-v4-flash|deepseek-chat|deepseek-reasoner)$",
    )
    session_id: Optional[str] = Field(None, description="会话ID，用于短期记忆")
    local_source: str = Field(
        "both",
        description="本地检索数据源: stream=文献上新 | journals=顶刊追踪 | both=文献上新及顶刊追踪",
        pattern="^(stream|journals|both)$",
    )
    
    @model_validator(mode="before")
    @classmethod
    def _alias_agent_mode(cls, data):
        if isinstance(data, dict) and "use_agent" not in data and "agent_mode" in data:
            data["use_agent"] = bool(data.get("agent_mode"))
        return data
    
    class Config:
        json_schema_extra = {
            "example": {
                "query": "High-intensity interval training对心血管健康的影响",
                "sports_gate": False,
                "use_agent": False,
                "top_k": 10,
                "lang": "zh"
            }
        }


class Citation(BaseModel):
    """引用"""
    idx: int
    pmid: Optional[str] = None  # ✅ 修复：支持没有PMID的journal文章
    title: str
    url: str
    journal_name: Optional[str] = None
    publication_year: Optional[int] = None


class AssistantChatResponse(BaseModel):
    """AI助手聊天响应（非流式）"""
    answer: str = Field(..., description="回答文本（带引用标记[n]）")
    citations: List[Citation] = Field(..., description="引用列表")
    recall_stats: Dict = Field(..., description="召回统计")
    performance: Dict = Field(..., description="性能指标")
    reasoning: Optional[List[str]] = Field(
        default=None,
        description="DeepSeek返回的思维链（按步骤分段）",
    )
    stream_token_type: str = Field(
        default="token",
        description="流式推送时使用的token类型（token|chain|status等）",
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "answer": "高强度间歇训练（HIIT）能够显著改善最大摄氧量[1]。研究表明HIIT对心血管健康有多方面的益处[2, 3]。",
                "citations": [
                    {
                        "idx": 1,
                        "pmid": "38123456",
                        "title": "Effects of HIIT on VO2max",
                        "url": "https://pubmed.ncbi.nlm.nih.gov/38123456/",
                        "journal_name": "Sports Medicine",
                        "publication_year": 2024
                    }
                ],
                "recall_stats": {
                    "literature_count": 8,
                    "journals_count": 5,
                    "final_count": 10
                },
                "performance": {
                    "search_duration_ms": 150,
                    "generation_duration_ms": 2500,
                    "total_duration_ms": 2650
                },
                "reasoning": [
                    "Step 1: 分析用户问题并确认需要回答的范围。",
                    "Step 2: 对比候选文献，筛选关键证据。"
                ],
                "stream_token_type": "token"
            }
        }


class ExportNbibRequest(BaseModel):
    """导出NBIB请求"""
    pmids: List[str] = Field(..., description="PMID列表", min_length=1, max_length=50)
    
    class Config:
        json_schema_extra = {
            "example": {
                "pmids": ["38123456", "38123457", "38123458"]
            }
        }
