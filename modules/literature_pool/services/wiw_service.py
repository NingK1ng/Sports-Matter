"""
WiW Service - WiW卡片生成和复用服务

实现WiW生成、复用逻辑和过期管理
"""
import hashlib
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import select, text, func, and_, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from modules.literature_pool.models.subscription import PoolSubscription
from modules.literature_pool.models.wiw_card import PoolWiWCard
from modules.research_gap.models.wiw import WiWResult
from modules.research_gap.services.wiw_generator import WiWGenerator


class WiWService:
    """WiW服务"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.wiw_generator = WiWGenerator()
    
    def _generate_input_fingerprint(self, pmid: str) -> str:
        """
        生成输入指纹（用于WiW复用）
        
        Args:
            pmid: PubMed ID
        
        Returns:
            MD5 hash
        """
        return hashlib.md5(pmid.encode()).hexdigest()
    
    async def check_existing_wiw(self, pmid: str) -> Optional[WiWResult]:
        """
        检查是否存在可复用的WiW结果
        
        Args:
            pmid: PubMed ID
        
        Returns:
            WiW结果对象，不存在或已过期返回None
        """
        fingerprint = self._generate_input_fingerprint(pmid)
        thirty_days_ago = datetime.now() - timedelta(days=30)
        
        stmt = select(WiWResult).where(
            and_(
                WiWResult.input_fingerprint == fingerprint,
                WiWResult.created_at >= thirty_days_ago
            )
        ).order_by(WiWResult.created_at.desc())
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def generate_or_reuse_wiw(
        self,
        pmid: str,
        subscription_id: int,
        track: str
    ) -> PoolWiWCard:
        """
        生成或复用WiW卡片
        
        Args:
            pmid: PubMed ID
            subscription_id: 订阅ID
            track: 轨道类型（stream/journals）
        
        Returns:
            WiW卡片映射对象
        
        Raises:
            ValueError: 生成失败
        """
        # 1. 检查是否可以复用
        existing_wiw = await self.check_existing_wiw(pmid)
        
        if existing_wiw:
            print(f"✅ 复用已有WiW结果: wiw_result_id={existing_wiw.id}, pmid={pmid}")
            wiw_result_id = existing_wiw.id
        else:
            # 2. 生成新的WiW
            print(f"🆕 生成新WiW: pmid={pmid}")
            wiw_data = await self.wiw_generator.generate_wiw(
                pmid=pmid,
                top_k=10,
                language="zh",
                enable_inspiration=True  # 强制开启顶刊推荐
            )
            
            # 3. 存储到wiw_results表
            fingerprint = self._generate_input_fingerprint(pmid)
            
            wiw_result = WiWResult(
                input_pmid=pmid,
                input_fingerprint=fingerprint,
                top_k=10,
                strategy_version="v1",
                template_version="v1",
                model_version=wiw_data["meta"].get("model_version", "deepseek-v4-flash"),
                language="zh",
                card_content=wiw_data["card"],
                references=wiw_data["references"],
                references_hash=hashlib.md5(
                    ",".join([ref["pmid"] for ref in wiw_data["references"]]).encode()
                ).hexdigest(),
                top_journal_recommendations=wiw_data.get("top_journal_recommendations", []),
                meta=wiw_data["meta"],
            )
            
            self.session.add(wiw_result)
            await self.session.flush()  # 获取ID但不提交
            
            wiw_result_id = wiw_result.id
        
        # 4. 创建映射记录（使用UTC时间，避免naive/aware冲突）
        from datetime import timezone as _tz
        utc_now = datetime.now(_tz.utc)
        expires_at = utc_now + timedelta(days=7)
        
        wiw_card = PoolWiWCard(
            subscription_id=subscription_id,
            track=track,
            wiw_result_id=wiw_result_id,
            source_pmid=pmid,
            generated_at=utc_now,
            expires_at=expires_at,
        )
        
        self.session.add(wiw_card)
        await self.session.commit()
        await self.session.refresh(wiw_card)
        
        return wiw_card
    
    async def get_subscription_wiw_cards(
        self,
        subscription_id: int,
        track: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取订阅的WiW卡片（联查wiw_results）
        
        Args:
            subscription_id: 订阅ID
            track: 轨道类型过滤（可选）
        
        Returns:
            WiW卡片列表（包含完整card JSON）
        """
        # 构建查询
        stmt = (
            select(PoolWiWCard, WiWResult)
            .join(WiWResult, PoolWiWCard.wiw_result_id == WiWResult.id)
            .where(PoolWiWCard.subscription_id == subscription_id)
        )
        
        if track:
            stmt = stmt.where(PoolWiWCard.track == track)
        
        stmt = stmt.order_by(PoolWiWCard.generated_at.desc())
        
        result = await self.session.execute(stmt)
        rows = result.all()
        
        # 组装返回数据
        cards = []
        from datetime import timezone as _tz
        utc_now = datetime.now(_tz.utc)
        
        for wiw_card, wiw_result in rows:
            exp = wiw_card.expires_at
            exp_aware = exp if getattr(exp, 'tzinfo', None) else exp.replace(tzinfo=_tz.utc)
            is_expired = exp_aware < utc_now
            
            cards.append({
                "id": wiw_card.id,
                "wiw_result_id": wiw_card.wiw_result_id,
                "source_pmid": wiw_card.source_pmid,
                "track": wiw_card.track,
                "generated_at": wiw_card.generated_at.isoformat(),
                "expires_at": wiw_card.expires_at.isoformat(),
                "is_expired": is_expired,
                # 将references与顶刊推荐合并进card，便于前端渲染“关联文献”
                "card": {
                    **(wiw_result.card_content or {}),
                    "references": getattr(wiw_result, "references", []) or [],
                    "top_journal_recommendations": getattr(wiw_result, "top_journal_recommendations", []) or [],
                },
            })
        
        return cards
    
    async def cleanup_expired_mappings(self, days: int = 7) -> int:
        """
        清理过期的映射记录
        
        Args:
            days: 过期多少天后删除
        
        Returns:
            删除的记录数
        """
        cutoff = datetime.now() - timedelta(days=days)
        
        stmt = delete(PoolWiWCard).where(
            PoolWiWCard.expires_at < cutoff
        )
        
        result = await self.session.execute(stmt)
        await self.session.commit()
        
        return result.rowcount
    
    async def cleanup_orphan_wiw_results(self, days: int = 90) -> int:
        """
        清理孤儿WiW结果（90天未被引用）
        
        Args:
            days: 未被引用多少天后删除
        
        Returns:
            删除的记录数
        """
        cutoff = datetime.now() - timedelta(days=days)
        
        # 查找孤儿WiW（在wiw_results中但不在pool_wiw_cards中）
        orphan_stmt = (
            select(WiWResult.id)
            .where(
                and_(
                    WiWResult.created_at < cutoff,
                    ~WiWResult.id.in_(
                        select(PoolWiWCard.wiw_result_id).distinct()
                    )
                )
            )
        )
        
        orphan_result = await self.session.execute(orphan_stmt)
        orphan_ids = [row[0] for row in orphan_result]
        
        if not orphan_ids:
            return 0
        
        # 删除孤儿WiW
        delete_stmt = delete(WiWResult).where(WiWResult.id.in_(orphan_ids))
        result = await self.session.execute(delete_stmt)
        await self.session.commit()
        
        return result.rowcount
