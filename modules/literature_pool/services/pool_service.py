"""
Pool Service - 文献池管理服务

实现模块1/2文献检索和候选池管理
"""
import hashlib
from typing import List, Tuple, Optional
from datetime import datetime, timedelta, date
from sqlalchemy import select, text, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from modules.literature_pool.models.subscription import PoolSubscription
from modules.literature_pool.models.article import PoolArticle
from modules.literature_pool.models.wiw_card import PoolWiWCard
from modules.literature_stream.services.search_service import LiteratureSearchService
from modules.journals.services.search_service import SearchService as JournalsSearchService
from modules.journals.models.journal import JournalArticle
from modules.literature_stream.models.literature import Literature


class PoolService:
    """文献池服务"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.lit_search_service = LiteratureSearchService(session)
        self.journals_search_service = JournalsSearchService(session)
    
    async def search_and_add_stream_articles(
        self,
        subscription: PoolSubscription,
        limit: int = 50
    ) -> int:
        """
        搜索模块1文献并添加到候选池
        
        Args:
            subscription: 订阅对象
            limit: 最多添加多少篇
        
        Returns:
            添加的文献数量
        """
        # 构建tsquery
        query_text = subscription.query_text
        tsquery_sql, params = self.lit_search_service.build_tsquery(query_text)
        
        if not tsquery_sql:
            return 0
        
        # 查询模块1文献（最近30天）
        thirty_days_ago = datetime.now() - timedelta(days=30)
        
        # 排除已在池中的文献
        existing_lit_ids_stmt = select(PoolArticle.literature_id).where(
            PoolArticle.subscription_id == subscription.id
        )
        existing_lit_ids_result = await self.session.execute(existing_lit_ids_stmt)
        existing_lit_ids = set(row[0] for row in existing_lit_ids_result)
        
        # 全文检索
        search_condition = text(f"(title_vector || abstract_vector) @@ {tsquery_sql}")
        
        # 构建查询条件
        conditions = [
            search_condition,
            Literature.publication_date >= thirty_days_ago.date(),
            Literature.pmid.isnot(None),
        ]
        # 仅在有已存在文献时添加排除条件
        if existing_lit_ids:
            conditions.append(Literature.id.notin_(existing_lit_ids))
        
        stmt = (
            select(Literature)
            .where(and_(*conditions))
            .params(**params)
            .order_by(Literature.publication_date.desc())
            .limit(limit)
        )
        
        result = await self.session.execute(stmt)
        articles = result.scalars().all()
        
        # 添加到候选池
        added_count = 0
        for article in articles:
            pool_article = PoolArticle(
                subscription_id=subscription.id,
                literature_id=article.id,
                pmid=article.pmid,
                title=article.title,
            )
            self.session.add(pool_article)
            added_count += 1
        
        await self.session.commit()
        
        return added_count
    
    async def get_candidate_articles_journals(
        self,
        subscription: PoolSubscription,
        limit: int = 50
    ) -> List[JournalArticle]:
        """
        获取模块2候选文献（实时查询，不落库）
        
        Args:
            subscription: 订阅对象
            limit: 最多返回多少篇
        
        Returns:
            文献列表
        """
        query_text = subscription.query_text
        
        # 使用模块2的搜索服务
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        two_days_ago = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
        
        articles, total = await self.journals_search_service.search_articles(
            keywords=query_text,
            search_scope="tiab",
            since=thirty_days_ago,
            until=two_days_ago,  # 2天门槛：过滤掉最近2天的文章
            sort_by="date",
            page=1,
            per_page=limit
        )
        
        return articles
    
    async def get_random_stream_articles(
        self,
        subscription_id: int,
        count: int = 5
    ) -> List[PoolArticle]:
        """
        从模块1候选池随机选择文献
        
        Args:
            subscription_id: 订阅ID
            count: 需要多少篇
        
        Returns:
            随机选择的文献列表
        """
        # 排除已生成WiW的PMID
        generated_pmids_stmt = select(PoolWiWCard.source_pmid).where(
            and_(
                PoolWiWCard.subscription_id == subscription_id,
                PoolWiWCard.track == 'stream'
            )
        )
        generated_pmids_result = await self.session.execute(generated_pmids_stmt)
        generated_pmids = set(row[0] for row in generated_pmids_result)
        
        # 随机选择
        conditions = [PoolArticle.subscription_id == subscription_id]
        if generated_pmids:
            conditions.append(PoolArticle.pmid.notin_(generated_pmids))
        
        stmt = (
            select(PoolArticle)
            .where(and_(*conditions))
            .order_by(text("RANDOM()"))
            .limit(count)
        )
        
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def get_random_journals_articles(
        self,
        subscription: PoolSubscription,
        count: int = 2
    ) -> List[JournalArticle]:
        """
        从模块2候选文献中随机选择
        
        Args:
            subscription: 订阅对象
            count: 需要多少篇
        
        Returns:
            随机选择的文献列表
        """
        # 获取候选文献
        candidates = await self.get_candidate_articles_journals(subscription, limit=100)
        
        if not candidates:
            return []
        
        # 排除已生成WiW的PMID
        generated_pmids_stmt = select(PoolWiWCard.source_pmid).where(
            and_(
                PoolWiWCard.subscription_id == subscription.id,
                PoolWiWCard.track == 'journals'
            )
        )
        generated_pmids_result = await self.session.execute(generated_pmids_stmt)
        generated_pmids = set(row[0] for row in generated_pmids_result)
        
        # 过滤并随机选择
        filtered_candidates = [
            article for article in candidates
            if article.pmid and article.pmid not in generated_pmids
        ]
        
        if not filtered_candidates:
            return []
        
        # 随机选择（使用Python的random，因为candidates已经是内存列表）
        import random
        selected_count = min(count, len(filtered_candidates))
        selected = random.sample(filtered_candidates, selected_count)
        
        return selected
