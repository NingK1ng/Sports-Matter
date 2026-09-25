"""
Subscription Service - 订阅管理服务

实现订阅CRUD和3个订阅限制
"""
from typing import List, Optional
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from modules.literature_pool.models.subscription import PoolSubscription
from modules.literature_pool.models.wiw_card import PoolWiWCard
from modules.literature_pool.models.article import PoolArticle


class SubscriptionService:
    """订阅服务"""
    
    MAX_SUBSCRIPTIONS_PER_USER = 3
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_user_subscriptions(self, user_id: int) -> List[PoolSubscription]:
        """
        获取用户的所有订阅
        
        Args:
            user_id: 用户ID
        
        Returns:
            订阅列表
        """
        stmt = (
            select(PoolSubscription)
            .where(PoolSubscription.user_id == user_id)
            .order_by(PoolSubscription.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def get_subscription_by_id(
        self,
        subscription_id: int,
        user_id: int
    ) -> Optional[PoolSubscription]:
        """
        获取指定订阅（确保属于该用户）
        
        Args:
            subscription_id: 订阅ID
            user_id: 用户ID
        
        Returns:
            订阅对象，未找到或不属于该用户返回None
        """
        stmt = select(PoolSubscription).where(
            PoolSubscription.id == subscription_id,
            PoolSubscription.user_id == user_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def count_user_subscriptions(self, user_id: int) -> int:
        """
        统计用户的订阅数量
        
        Args:
            user_id: 用户ID
        
        Returns:
            订阅数量
        """
        stmt = select(func.count()).select_from(PoolSubscription).where(
            PoolSubscription.user_id == user_id
        )
        result = await self.session.execute(stmt)
        return result.scalar()
    
    async def create_subscription(
        self,
        user_id: int,
        title: str,
        query_text: str
    ) -> PoolSubscription:
        """
        创建订阅
        
        Args:
            user_id: 用户ID
            title: 订阅标题
            query_text: 查询文本
        
        Returns:
            创建的订阅对象
        
        Raises:
            ValueError: 超过订阅数量限制
        """
        # 检查订阅数量限制
        count = await self.count_user_subscriptions(user_id)
        if count >= self.MAX_SUBSCRIPTIONS_PER_USER:
            raise ValueError(
                f"SUBSCRIPTION_LIMIT_EXCEEDED: 每个用户最多{self.MAX_SUBSCRIPTIONS_PER_USER}个订阅"
            )
        
        # 创建订阅
        subscription = PoolSubscription(
            user_id=user_id,
            title=title,
            query_text=query_text,
            is_active=1,
        )
        
        self.session.add(subscription)
        await self.session.commit()
        await self.session.refresh(subscription)
        
        # ✅ 订阅创建后立即触发异步搜索（双保险方案）
        try:
            from modules.literature_pool.tasks.search_tasks import search_stream_articles_task
            search_stream_articles_task.delay(subscription.id)
        except Exception as e:
            # 不阻塞订阅创建流程，仅记录错误
            import logging
            logging.warning(f"Failed to trigger search task for subscription {subscription.id}: {e}")
        
        return subscription
    
    async def update_subscription(
        self,
        subscription_id: int,
        user_id: int,
        title: Optional[str] = None,
        query_text: Optional[str] = None,
        is_active: Optional[int] = None
    ) -> Optional[PoolSubscription]:
        """
        更新订阅
        
        Args:
            subscription_id: 订阅ID
            user_id: 用户ID
            title: 新标题（可选）
            query_text: 新查询文本（可选）
            is_active: 是否激活（可选）
        
        Returns:
            更新后的订阅对象，未找到返回None
        """
        subscription = await self.get_subscription_by_id(subscription_id, user_id)
        if not subscription:
            return None
        
        if title is not None:
            subscription.title = title
        if query_text is not None:
            subscription.query_text = query_text
        if is_active is not None:
            subscription.is_active = is_active
        
        await self.session.commit()
        await self.session.refresh(subscription)
        
        return subscription
    
    async def delete_subscription(
        self,
        subscription_id: int,
        user_id: int
    ) -> bool:
        """
        删除订阅（级联删除相关的文献池和WiW卡片）
        
        Args:
            subscription_id: 订阅ID
            user_id: 用户ID
        
        Returns:
            是否删除成功
        """
        subscription = await self.get_subscription_by_id(subscription_id, user_id)
        if not subscription:
            return False
        
        await self.session.delete(subscription)
        await self.session.commit()
        
        return True
    
    async def refresh_subscription(
        self,
        subscription_id: int,
        user_id: int
    ) -> bool:
        """
        刷新订阅（清空现有映射记录）
        
        Args:
            subscription_id: 订阅ID
            user_id: 用户ID
        
        Returns:
            是否刷新成功
        """
        subscription = await self.get_subscription_by_id(subscription_id, user_id)
        if not subscription:
            return False
        
        # 删除该订阅的所有WiW卡片映射
        stmt = delete(PoolWiWCard).where(
            PoolWiWCard.subscription_id == subscription_id
        )
        await self.session.execute(stmt)
        
        # 删除该订阅的所有文献池记录
        stmt = delete(PoolArticle).where(
            PoolArticle.subscription_id == subscription_id
        )
        await self.session.execute(stmt)
        
        await self.session.commit()
        
        return True
