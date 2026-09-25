"""
WiW Tasks - WiW生成任务

定时生成双轨道WiW卡片
"""
import random
from celery import shared_task
from sqlalchemy import select, func
from datetime import datetime, timedelta

from core.database import get_db_session
from modules.literature_pool.models.subscription import PoolSubscription
from modules.literature_pool.models.user import User
from modules.literature_pool.services.pool_service import PoolService
from modules.literature_pool.services.wiw_service import WiWService


@shared_task(name="literature_pool.generate_stream_wiw", bind=True, max_retries=3)
def generate_stream_wiw_task(self, subscription_id: int) -> dict:
    """
    生成模块1轨道WiW任务（单个订阅）
    
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
                now_utc = datetime.now(timezone.utc)
                seven_days_ago = now_utc - timedelta(days=7)
                # 确保last_login_at为ware
                last_login_aware = user.last_login_at
                if last_login_aware.tzinfo is None:
                    last_login_aware = last_login_aware.replace(tzinfo=timezone.utc)
                if last_login_aware < seven_days_ago:
                    return {"status": "skipped", "reason": "user_inactive"}
            
            # 随机选择1篇文献
            pool_service = PoolService(session)
            articles = await pool_service.get_random_stream_articles(subscription_id, count=1)
            
            if not articles:
                return {"status": "skipped", "reason": "no_candidate_articles"}
            
            article = articles[0]
            
            # 生成或复用WiW
            try:
                wiw_service = WiWService(session)
                wiw_card = await wiw_service.generate_or_reuse_wiw(
                    pmid=article.pmid,
                    subscription_id=subscription_id,
                    track="stream"
                )
                
                return {
                    "status": "success",
                    "subscription_id": subscription_id,
                    "wiw_card_id": wiw_card.id,
                    "pmid": article.pmid
                }
            
            except ValueError as e:
                error_msg = str(e)
                
                # ELink召回不足或LLM失败，重试
                if "LOW_RECALL" in error_msg or "LLM_" in error_msg:
                    raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
                
                return {"status": "failed", "error": error_msg}
    
    return asyncio.run(_run())


@shared_task(name="literature_pool.generate_journals_wiw", bind=True, max_retries=3)
def generate_journals_wiw_task(self, subscription_id: int) -> dict:
    """
    生成模块2轨道WiW任务（单个订阅，每日2张）
    
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
                now_utc = datetime.now(timezone.utc)
                seven_days_ago = now_utc - timedelta(days=7)
                # 确保last_login_at为ware
                last_login_aware = user.last_login_at
                if last_login_aware.tzinfo is None:
                    last_login_aware = last_login_aware.replace(tzinfo=timezone.utc)
                if last_login_aware < seven_days_ago:
                    return {"status": "skipped", "reason": "user_inactive"}
            
            # 随机选择2篇文献
            pool_service = PoolService(session)
            articles = await pool_service.get_random_journals_articles(subscription, count=2)
            
            if not articles:
                return {"status": "skipped", "reason": "no_candidate_articles"}
            
            # 生成或复用WiW
            generated_cards = []
            failed_cards = []
            
            for article in articles:
                if not article.pmid:
                    continue
                
                try:
                    wiw_service = WiWService(session)
                    wiw_card = await wiw_service.generate_or_reuse_wiw(
                        pmid=article.pmid,
                        subscription_id=subscription_id,
                        track="journals"
                    )
                    
                    generated_cards.append({
                        "wiw_card_id": wiw_card.id,
                        "pmid": article.pmid
                    })
                
                except ValueError as e:
                    error_msg = str(e)
                    failed_cards.append({
                        "pmid": article.pmid,
                        "error": error_msg
                    })
            
            return {
                "status": "success",
                "subscription_id": subscription_id,
                "generated_count": len(generated_cards),
                "failed_count": len(failed_cards),
                "generated_cards": generated_cards,
                "failed_cards": failed_cards
            }
    
    return asyncio.run(_run())


@shared_task(name="literature_pool.generate_all_subscriptions_wiw")
def generate_all_subscriptions_wiw_task() -> dict:
    """
    为所有订阅生成WiW卡片
    
    - 模块1轨道：每天分散生成5张（使用Celery延迟任务）
    - 模块2轨道：每日凌晨4点生成2张
    
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
            
            stream_tasks_scheduled = 0
            journals_tasks_scheduled = 0
            
            for subscription in subscriptions:
                # 检查用户活跃度
                user_stmt = select(User).where(User.id == subscription.user_id)
                user_result = await session.execute(user_stmt)
                user = user_result.scalar_one_or_none()
                
                if not user:
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
                        continue
                
                # 模块1轨道：创建5个延迟任务，分散到24小时内
                for i in range(5):
                    delay_seconds = random.randint(0, 86400)  # 0-24小时
                    generate_stream_wiw_task.apply_async(
                        args=[subscription.id],
                        countdown=delay_seconds
                    )
                    stream_tasks_scheduled += 1
                
                # 模块2轨道：立即执行（因为此任务本身在凌晨4点执行）
                generate_journals_wiw_task.apply_async(args=[subscription.id])
                journals_tasks_scheduled += 1
            
            return {
                "status": "success",
                "stream_tasks_scheduled": stream_tasks_scheduled,
                "journals_tasks_scheduled": journals_tasks_scheduled
            }
    
    return asyncio.run(_run())
