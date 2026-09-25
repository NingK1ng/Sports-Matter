"""
Subscriptions API - 订阅管理

提供订阅CRUD和刷新功能
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.literature_pool.api.auth import require_member_user
from modules.literature_pool.services.subscription_service import SubscriptionService
from modules.literature_pool.schemas.subscription import (
    SubscriptionCreate,
    SubscriptionUpdate,
    SubscriptionResponse,
    SubscriptionListResponse,
)

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])


@router.get("", response_model=SubscriptionListResponse)
async def get_subscriptions(
    user=Depends(require_member_user),
    db: AsyncSession = Depends(get_db)
):
    """
    获取当前用户的订阅列表（含统计信息）
    
    Args:
        current_user_id: 当前用户ID
        db: 数据库会话
    
    Returns:
        订阅列表及统计信息
    """
    from sqlalchemy import select, func
    from modules.literature_pool.models.article import PoolArticle
    from modules.literature_pool.models.wiw_card import PoolWiWCard
    
    service = SubscriptionService(db)
    subscriptions = await service.get_user_subscriptions(user.id)
    
    # 为每个订阅添加统计信息
    enriched_subs = []
    for sub in subscriptions:
        # 统计文献数
        article_count_stmt = select(func.count(PoolArticle.id)).where(
            PoolArticle.subscription_id == sub.id
        )
        article_result = await db.execute(article_count_stmt)
        article_count = article_result.scalar() or 0
        
        # 统计WiW数
        wiw_count_stmt = select(func.count(PoolWiWCard.id)).where(
            PoolWiWCard.subscription_id == sub.id
        )
        wiw_result = await db.execute(wiw_count_stmt)
        wiw_count = wiw_result.scalar() or 0
        
        # 最新生成时间
        latest_wiw_stmt = select(func.max(PoolWiWCard.generated_at)).where(
            PoolWiWCard.subscription_id == sub.id
        )
        latest_result = await db.execute(latest_wiw_stmt)
        latest_generated = latest_result.scalar()
        
        sub_dict = {
            **sub.__dict__,
            "article_count": article_count,
            "wiw_count": wiw_count,
            "latest_generated_at": latest_generated.isoformat() if latest_generated else None
        }
        enriched_subs.append(sub_dict)
    
    return SubscriptionListResponse(
        subscriptions=[SubscriptionResponse(**s) for s in enriched_subs],
        total=len(subscriptions)
    )


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
async def get_subscription(
    subscription_id: int,
    user=Depends(require_member_user),
    db: AsyncSession = Depends(get_db)
):
    """
    获取指定订阅
    
    Args:
        subscription_id: 订阅ID
    
    Returns:
        订阅详情
    
    Raises:
        HTTPException: 订阅不存在或无权访问
    """
    service = SubscriptionService(db)
    subscription = await service.get_subscription_by_id(subscription_id, user.id)
    
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在或无权访问")
    
    return SubscriptionResponse.model_validate(subscription)


@router.post("", response_model=SubscriptionResponse, status_code=201)
async def create_subscription(
    data: SubscriptionCreate,
    user=Depends(require_member_user),
    db: AsyncSession = Depends(get_db)
):
    """
    创建订阅
    
    Args:
        data: 订阅数据
    
    Returns:
        创建的订阅
    
    Raises:
        HTTPException: 超过订阅数量限制
    """
    service = SubscriptionService(db)
    
    try:
        title = (data.title or "").strip()
        query_text = (data.query_text or "").strip()
        if not query_text:
            raise ValueError("QUERY_TEXT_EMPTY: 查询文本不能为空")

        if not title:
            compact = " ".join(query_text.split())
            title = (compact[:80] + "…") if len(compact) > 80 else compact

        subscription = await service.create_subscription(
            user_id=user.id,
            title=title,
            query_text=query_text
        )
        
        return SubscriptionResponse.model_validate(subscription)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{subscription_id}", response_model=SubscriptionResponse)
async def update_subscription(
    subscription_id: int,
    data: SubscriptionUpdate,
    user=Depends(require_member_user),
    db: AsyncSession = Depends(get_db)
):
    """
    更新订阅
    
    Args:
        subscription_id: 订阅ID
        data: 更新数据
    
    Returns:
        更新后的订阅
    
    Raises:
        HTTPException: 订阅不存在或无权访问
    """
    service = SubscriptionService(db)
    
    subscription = await service.update_subscription(
        subscription_id=subscription_id,
        user_id=user.id,
        title=data.title,
        query_text=data.query_text,
        is_active=data.is_active
    )
    
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在或无权访问")
    
    return SubscriptionResponse.model_validate(subscription)


@router.delete("/{subscription_id}", status_code=204)
async def delete_subscription(
    subscription_id: int,
    user=Depends(require_member_user),
    db: AsyncSession = Depends(get_db)
):
    """
    删除订阅
    
    Args:
        subscription_id: 订阅ID
    
    Raises:
        HTTPException: 订阅不存在或无权访问
    """
    service = SubscriptionService(db)
    
    success = await service.delete_subscription(subscription_id, user.id)
    
    if not success:
        raise HTTPException(status_code=404, detail="订阅不存在或无权访问")


@router.post("/{subscription_id}/refresh", status_code=200)
async def refresh_subscription(
    subscription_id: int,
    user=Depends(require_member_user),
    db: AsyncSession = Depends(get_db)
):
    """
    刷新订阅（清空现有映射记录）
    
    Args:
        subscription_id: 订阅ID
    
    Returns:
        刷新结果
    
    Raises:
        HTTPException: 订阅不存在或无权访问
    """
    service = SubscriptionService(db)
    
    success = await service.refresh_subscription(subscription_id, user.id)
    
    if not success:
        raise HTTPException(status_code=404, detail="订阅不存在或无权访问")
    
    return {"message": "订阅已刷新，新卡片将在24小时内生成"}
