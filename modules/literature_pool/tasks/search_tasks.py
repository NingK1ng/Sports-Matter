"""
Search Tasks - 文献搜索任务

定时搜索模块1文献并添加到候选池
"""
from celery import shared_task
from sqlalchemy import select
from datetime import datetime, timedelta

from core.database import get_db_session
from modules.literature_pool.models.subscription import PoolSubscription
from modules.literature_pool.models.user import User
from modules.literature_pool.services.pool_service import PoolService


@shared_task(name="literature_pool.search_stream_articles")
def search_stream_articles_task(subscription_id: int) -> dict:
    """
    搜索模块1文献任务
    
    Args:
        subscription_id: 订阅ID
    
    Returns:
        任务结果
    """
    import asyncio
    from core.database import init_database, _engine
    
    async def _run():
        # 确保数据库已初始化
        if _engine is None:
            await init_database()
        
        async with get_db_session() as session:
            # 获取订阅
            stmt = select(PoolSubscription).where(
                PoolSubscription.id == subscription_id,
                PoolSubscription.is_active == 1
            )
            result = await session.execute(stmt)
            subscription = result.scalar_one_or_none()
            
            if not subscription:
                return {"status": "skipped", "reason": "subscription_not_found"}
            
            # 检查用户活跃度
            user_stmt = select(User).where(User.id == subscription.user_id)
            user_result = await session.execute(user_stmt)
            user = user_result.scalar_one_or_none()
            
            if not user:
                return {"status": "skipped", "reason": "user_not_found"}
            
            # 7天未登录则跳过（使用timezone-aware datetime）
            if user.last_login_at:
                from datetime import timezone
                seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
                if user.last_login_at < seven_days_ago:
                    return {
                        "status": "skipped",
                        "reason": "user_inactive",
                        "last_login": user.last_login_at.isoformat()
                    }
            
            # 搜索文献
            pool_service = PoolService(session)
            added_count = await pool_service.search_and_add_stream_articles(
                subscription, limit=50
            )
            
            return {
                "status": "success",
                "subscription_id": subscription_id,
                "added_count": added_count
            }
    
    return asyncio.run(_run())


@shared_task(name="literature_pool.search_all_subscriptions_stream")
def search_all_subscriptions_stream_task() -> dict:
    """
    搜索所有订阅的模块1文献（每日凌晨3点）
    
    Returns:
        任务结果
    """
    import asyncio
    from core.database import init_database, _engine
    
    async def _run():
        # 确保数据库已初始化
        if _engine is None:
            await init_database()
        
        async with get_db_session() as session:
            # 获取所有激活的订阅
            stmt = select(PoolSubscription).where(
                PoolSubscription.is_active == 1
            )
            result = await session.execute(stmt)
            subscriptions = result.scalars().all()
            
            total_count = 0
            processed_count = 0
            skipped_count = 0
            
            for subscription in subscriptions:
                # 检查用户活跃度
                user_stmt = select(User).where(User.id == subscription.user_id)
                user_result = await session.execute(user_stmt)
                user = user_result.scalar_one_or_none()
                
                if not user:
                    skipped_count += 1
                    continue
                
                # 7天未登录则跳过（使用timezone-aware datetime）
                if user.last_login_at:
                    from datetime import timezone
                    now_utc = datetime.now(timezone.utc)
                    seven_days_ago = now_utc - timedelta(days=7)
                    # 确保last_login_at为ware
                    last_login_aware = user.last_login_at
                    if last_login_aware.tzinfo is None:
                        last_login_aware = last_login_aware.replace(tzinfo=timezone.utc)
                    if last_login_aware < seven_days_ago:
                        skipped_count += 1
                        continue
                
                # 搜索文献
                pool_service = PoolService(session)
                added_count = await pool_service.search_and_add_stream_articles(
                    subscription, limit=50
                )
                
                total_count += added_count
                processed_count += 1
            
            return {
                "status": "success",
                "processed_subscriptions": processed_count,
                "skipped_subscriptions": skipped_count,
                "total_articles_added": total_count
            }
    
    return asyncio.run(_run())
