"""
Feed API - Feed流展示

提供双轨道WiW卡片和文献列表
"""
from typing import List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.cache import cache_get, cache_set
from modules.literature_pool.api.auth import require_member_user
from modules.literature_pool.services.subscription_service import SubscriptionService
from modules.literature_pool.services.pool_service import PoolService
from modules.literature_pool.services.wiw_service import WiWService
from modules.literature_pool.schemas.feed import (
    FeedResponse,
    WiWCardResponse,
    ArticleResponse,
)

router = APIRouter(prefix="/feed", tags=["Feed"])


@router.get("/{subscription_id}", response_model=FeedResponse)
async def get_feed(
    subscription_id: int,
    user=Depends(require_member_user),
    db: AsyncSession = Depends(get_db)
):
    """
    获取订阅的Feed流（两轨道卡片汇总）
    
    Args:
        subscription_id: 订阅ID
    
    Returns:
        Feed流数据
    
    Raises:
        HTTPException: 订阅不存在或无权访问
    """
    # 验证订阅权限
    sub_service = SubscriptionService(db)
    subscription = await sub_service.get_subscription_by_id(subscription_id, user.id)
    
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在或无权访问")
    
    # 获取WiW卡片
    wiw_service = WiWService(db)
    
    # 模块1轨道卡片（最多5张）
    stream_cards = await wiw_service.get_subscription_wiw_cards(
        subscription_id, track="stream"
    )
    stream_cards = stream_cards[:5]  # 限制5张
    
    # 模块2轨道卡片（最多2张）
    journals_cards = await wiw_service.get_subscription_wiw_cards(
        subscription_id, track="journals"
    )
    journals_cards = journals_cards[:2]  # 限制2张
    
    # 模块2文献列表（实时查询+缓存）
    cache_key = f"pool:journals_articles:{subscription_id}"
    journals_articles = await cache_get(cache_key)
    
    if journals_articles is None:
        pool_service = PoolService(db)
        articles = await pool_service.get_candidate_articles_journals(subscription, limit=20)
        
        # 转换为DTO（确保所有date对象转为字符串用于缓存）
        journals_articles = []
        for article in articles:
            article_dict = {
                "id": article.id,
                "doi": article.doi,
                "title": article.title,
                "abstract": article.abstract,
                "abstract_source": article.abstract_source or "unknown",
                "authors": article.authors or [],
                "published_at_precise": article.published_at_precise.isoformat() if article.published_at_precise else (article.publication_date.isoformat() if article.publication_date else datetime.now().date().isoformat()),
                "publication_date": article.publication_date.isoformat() if article.publication_date else datetime.now().date().isoformat(),  # 转为字符串
                "journal_issn": article.journal_issn,
                "journal_name": article.journal_name,
                "category": article.category or "unknown",
                "cited_by_count": article.cited_by_count,
                "cited_by_percentile_year": article.cited_by_percentile_year,
                "labels": article.labels or [],
            }
            journals_articles.append(article_dict)
        
        # 缓存5分钟
        await cache_set(cache_key, journals_articles, ttl=300)
    
    return FeedResponse(
        stream_cards=[WiWCardResponse(**card) for card in stream_cards],
        journals_cards=[WiWCardResponse(**card) for card in journals_cards],
        journals_articles=[ArticleResponse(**article) for article in journals_articles],
        total_stream_cards=len(stream_cards),
        total_journals_cards=len(journals_cards),
        total_journals_articles=len(journals_articles)
    )


@router.get("/{subscription_id}/track/{track}", response_model=List[WiWCardResponse])
async def get_feed_by_track(
    subscription_id: int,
    track: str,
    user=Depends(require_member_user),
    db: AsyncSession = Depends(get_db)
):
    """
    获取指定轨道的卡片
    
    Args:
        subscription_id: 订阅ID
        track: 轨道类型（stream/journals）
    
    Returns:
        WiW卡片列表
    
    Raises:
        HTTPException: 订阅不存在或无权访问
    """
    if track not in ["stream", "journals"]:
        raise HTTPException(status_code=400, detail="轨道类型无效，必须是stream或journals")
    
    # 验证订阅权限
    sub_service = SubscriptionService(db)
    subscription = await sub_service.get_subscription_by_id(subscription_id, user.id)
    
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在或无权访问")
    
    # 获取卡片
    wiw_service = WiWService(db)
    cards = await wiw_service.get_subscription_wiw_cards(subscription_id, track=track)
    
    # 限制数量
    limit = 5 if track == "stream" else 2
    cards = cards[:limit]
    
    return [WiWCardResponse(**card) for card in cards]
