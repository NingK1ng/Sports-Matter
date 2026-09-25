"""
Subscription API Schemas
"""
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class SubscriptionCreate(BaseModel):
    """创建订阅请求"""
    title: Optional[str] = Field(None, min_length=1, max_length=200, description="订阅标题（可选，默认使用query_text）")
    query_text: str = Field(..., min_length=1, max_length=500, description="查询文本")


class SubscriptionUpdate(BaseModel):
    """更新订阅请求"""
    title: str | None = Field(None, min_length=1, max_length=200, description="订阅标题")
    query_text: str | None = Field(None, min_length=1, max_length=500, description="查询文本")
    is_active: int | None = Field(None, ge=0, le=1, description="是否激活")


class SubscriptionResponse(BaseModel):
    """订阅响应（含统计信息）"""
    id: int
    user_id: int
    title: str
    query_text: str
    is_active: int
    created_at: datetime
    updated_at: datetime
    article_count: Optional[int] = 0  # 文献数量
    wiw_count: Optional[int] = 0  # WiW卡片数量
    latest_generated_at: Optional[str] = None  # 最新生成时间
    
    class Config:
        from_attributes = True


class SubscriptionListResponse(BaseModel):
    """订阅列表响应"""
    subscriptions: List[SubscriptionResponse]
    total: int
