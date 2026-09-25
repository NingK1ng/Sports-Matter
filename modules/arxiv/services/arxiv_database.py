"""
arXiv数据库服务
提供文章入库、更新、查询功能
"""
import logging
import re
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
from sqlalchemy import select, func, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from modules.arxiv.models.arxiv_article import ArxivArticle
from modules.arxiv.models.arxiv_crawl_log import ArxivCrawlLog
from modules.arxiv.models.arxiv_category_config import ArxivCategoryConfig

logger = logging.getLogger(__name__)


class ArxivDatabaseService:
    """arXiv数据库服务"""

    def __init__(self, session: AsyncSession):
        """
        初始化数据库服务

        Args:
            session: 异步数据库会话
        """
        self.session = session

    async def upsert_articles(self, articles: List[Dict]) -> Tuple[int, int]:
        """
        批量插入或更新文章（幂等操作）

        Args:
            articles: 文章列表

        Returns:
            (new_inserted, updated_count): 新增数量和更新数量
        """
        new_inserted = 0
        updated_count = 0

        for article in articles:
            arxiv_id = article["arxiv_id"]

            # 检查文章是否已存在
            stmt = select(ArxivArticle).where(ArxivArticle.arxiv_id == arxiv_id)
            result = await self.session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                # 更新现有记录（保留旧分类）
                existing.version = article.get("version", existing.version)
                existing.title = article["title"]
                existing.abstract = article.get("abstract")
                incoming_title_zh = article.get("title_zh")
                if incoming_title_zh is not None and str(incoming_title_zh).strip():
                    existing.title_zh = str(incoming_title_zh).strip()
                incoming_abstract_zh = article.get("abstract_zh")
                if incoming_abstract_zh is not None and str(incoming_abstract_zh).strip():
                    existing.abstract_zh = str(incoming_abstract_zh).strip()
                existing.authors = article.get("authors")
                existing.published_date = article.get("published_date")
                existing.updated_date = article.get("updated_date")
                existing.submitted_date = article.get("submitted_date")
                existing.pdf_url = article.get("pdf_url")
                existing.abs_url = article.get("abs_url")
                existing.primary_category = article.get("primary_category")
                existing.categories = article.get("categories")
                # 保留旧分类（不重新分类）
                # existing.sport_category = ...
                # existing.sport_relevance = ...
                existing.updated_at = datetime.utcnow()

                updated_count += 1
                logger.debug(f"更新文章: {arxiv_id}")
            else:
                incoming_title_zh = article.get("title_zh")
                if incoming_title_zh is not None and str(incoming_title_zh).strip():
                    incoming_title_zh = str(incoming_title_zh).strip()
                else:
                    incoming_title_zh = None
                incoming_abstract_zh = article.get("abstract_zh")
                if incoming_abstract_zh is not None and str(incoming_abstract_zh).strip():
                    incoming_abstract_zh = str(incoming_abstract_zh).strip()
                else:
                    incoming_abstract_zh = None
                # 插入新记录
                new_article = ArxivArticle(
                    arxiv_id=arxiv_id,
                    version=article.get("version", 1),
                    source=article.get("source", "arxiv"),
                    title=article["title"],
                    title_zh=incoming_title_zh,
                    abstract=article.get("abstract"),
                    abstract_zh=incoming_abstract_zh,
                    primary_category=article.get("primary_category"),
                    categories=article.get("categories"),
                    sport_category=article.get("sport_category"),
                    sport_relevance=article.get("sport_relevance"),
                    authors=article.get("authors"),
                    published_date=article.get("published_date"),
                    updated_date=article.get("updated_date"),
                    submitted_date=article.get("submitted_date"),
                    pdf_url=article.get("pdf_url"),
                    abs_url=article.get("abs_url"),
                    crawled_at=datetime.utcnow(),
                    is_deleted=False,
                )
                self.session.add(new_article)
                new_inserted += 1
                logger.debug(f"新增文章: {arxiv_id}")

        await self.session.commit()
        logger.info(f"批量入库完成：新增{new_inserted}篇，更新{updated_count}篇")
        return new_inserted, updated_count

    async def log_crawl_task(
        self,
        task_type: str,
        source: str,
        status: str,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        batch_number: Optional[int] = None,
        total_fetched: int = 0,
        llm_processed: int = 0,
        new_inserted: int = 0,
        updated_count: int = 0,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> int:
        """
        记录爬取任务日志

        Args:
            task_type: 任务类型（incremental/backfill）
            source: 来源（arxiv/biorxiv）
            status: 状态（running/success/failed）
            date_from: 起始日期
            date_to: 结束日期
            batch_number: 批次号
            total_fetched: L1召回数
            llm_processed: L2处理数
            new_inserted: 新增入库数
            updated_count: 更新数
            error_message: 错误信息
            started_at: 开始时间
            finished_at: 结束时间

        Returns:
            日志ID
        """
        log = ArxivCrawlLog(
            task_type=task_type,
            source=source,
            status=status,
            date_from=date_from,
            date_to=date_to,
            batch_number=batch_number,
            total_fetched=total_fetched,
            llm_processed=llm_processed,
            new_inserted=new_inserted,
            updated_count=updated_count,
            error_message=error_message,
            started_at=started_at or datetime.utcnow(),
            finished_at=finished_at,
        )
        self.session.add(log)
        await self.session.commit()
        await self.session.refresh(log)
        return log.id

    async def get_articles(
        self,
        category: Optional[str] = None,
        keywords: Optional[str] = None,
        search_scope: str = "tiab",
        source: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        created_since: Optional[datetime] = None,
        created_until: Optional[datetime] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> Tuple[List[ArxivArticle], int]:
        """
        分页查询文章

        Args:
            category: 运动科学分类过滤（目前已弱化，可忽略）
            keywords: 关键词搜索
            search_scope: 搜索范围 ti|tiab
            source: 数据来源：arxiv/biorxiv（None 或 "all" 表示全部）
            date_from: 起始日期
            date_to: 结束日期
            page: 页码
            per_page: 每页数量

        Returns:
            (文章列表, 总数)
        """
        # 构建查询条件
        conditions = [ArxivArticle.is_deleted == False]

        if category:
            conditions.append(ArxivArticle.sport_category == category)

        if source and source != "all":
            logger.info(f"Filtering by source: {source}")
            conditions.append(ArxivArticle.source == source)
        else:
            logger.info(f"No source filter applied (source={source})")

        if date_from:
            conditions.append(ArxivArticle.submitted_date >= date_from)

        if date_to:
            conditions.append(ArxivArticle.submitted_date <= date_to)

        # 入库时间过滤（created_at 存储为 UTC naive）
        if created_since:
            conditions.append(ArxivArticle.created_at >= created_since)
        if created_until:
            conditions.append(ArxivArticle.created_at <= created_until)

        # 关键词全文检索（与模块1对齐：支持 ti / tiab，支持短语和布尔查询）
        ts_params: Dict[str, str] = {}
        if keywords:
            # 支持直接用 arXiv ID 查询（常见：2601.00216 / arXiv:2601.00216 / URL / 带版本号）
            # 若输入基本等同于 arXiv ID，则走精确匹配，避免全文检索对数字不友好导致 0 结果。
            arxiv_id_candidate: Optional[str] = None
            kw_lower = str(keywords).strip().lower()
            kw_lower = re.sub(r"^arxiv\s*:\s*", "", kw_lower)
            kw_lower = re.sub(r"^https?://(www\.)?arxiv\.org/abs/", "", kw_lower)
            kw_lower = kw_lower.strip()
            kw_lower = re.sub(r"v\d+$", "", kw_lower)

            m = re.fullmatch(r"\d{4}\.\d{4,5}", kw_lower)
            if m:
                arxiv_id_candidate = kw_lower
            else:
                # old-style: archive/YYMMNNN
                m_old = re.fullmatch(r"[a-z-]+/\d{7}", kw_lower)
                if m_old:
                    arxiv_id_candidate = kw_lower

            if arxiv_id_candidate:
                conditions.append(ArxivArticle.arxiv_id == arxiv_id_candidate)
            else:
                # 清洗查询：保留 & | ! 引号 和 连字符，合并多空格
                cleaned = re.sub(r"[^\w\s&|!\'\"-]", " ", keywords)
                cleaned = re.sub(r"\s+", " ", cleaned).strip()

                if cleaned:
                    # 选择 tsquery 函数
                    if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) > 2:
                        tsquery_sql = "phraseto_tsquery('english', unaccent(:kw))"
                        ts_params = {"kw": cleaned.strip('"')}
                    elif any(op in cleaned for op in ("&", "|", "!")):
                        tsquery_sql = "to_tsquery('english', unaccent(:kw))"
                        ts_params = {"kw": cleaned}
                    else:
                        tsquery_sql = "plainto_tsquery('english', unaccent(:kw))"
                        ts_params = {"kw": cleaned}

                    if search_scope == "ti":
                        search_condition = text(f"title_vector @@ {tsquery_sql}")
                    else:
                        search_condition = text(f"(title_vector || abstract_vector) @@ {tsquery_sql}")

                    conditions.append(search_condition)

        # 查询总数
        count_stmt = select(func.count()).select_from(ArxivArticle).where(and_(*conditions))
        if ts_params:
            count_stmt = count_stmt.params(**ts_params)
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar()

        # 查询文章列表
        stmt = (
            select(ArxivArticle)
            .where(and_(*conditions))
            .order_by(
                ArxivArticle.created_at.desc()
                if (created_since or created_until)
                else ArxivArticle.submitted_date.desc()
            )
            .offset((page - 1) * per_page)
            .limit(per_page)
        )

        if ts_params:
            stmt = stmt.params(**ts_params)

        result = await self.session.execute(stmt)
        articles = result.scalars().all()

        return articles, total

    async def get_article_by_arxiv_id(self, arxiv_id: str) -> Optional[ArxivArticle]:
        """
        根据arxiv_id查询单篇文章

        Args:
            arxiv_id: arXiv ID

        Returns:
            文章对象或None
        """
        stmt = select(ArxivArticle).where(
            and_(ArxivArticle.arxiv_id == arxiv_id, ArxivArticle.is_deleted == False)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_category_stats(self) -> List[Dict]:
        """
        获取各分类统计

        Returns:
            分类统计列表
        """
        stmt = (
            select(
                ArxivArticle.sport_category,
                func.count(ArxivArticle.id).label("count"),
            )
            .where(
                and_(
                    ArxivArticle.is_deleted == False,
                    ArxivArticle.sport_category.isnot(None),
                )
            )
            .group_by(ArxivArticle.sport_category)
        )

        result = await self.session.execute(stmt)
        rows = result.all()

        stats = [{"category": row[0], "count": row[1]} for row in rows]
        return stats

    async def get_total_count(self) -> int:
        """
        获取文章总数

        Returns:
            总数
        """
        stmt = select(func.count()).select_from(ArxivArticle).where(ArxivArticle.is_deleted == False)
        result = await self.session.execute(stmt)
        return result.scalar()

    async def get_categories(self) -> List[ArxivCategoryConfig]:
        """
        获取4大分类配置

        Returns:
            分类列表
        """
        stmt = (
            select(ArxivCategoryConfig)
            .where(ArxivCategoryConfig.is_enabled == True)
            .order_by(ArxivCategoryConfig.display_order)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
