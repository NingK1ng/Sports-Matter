"""
数据加载服务 - 从数据库加载文献数据用于图谱构建
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from datetime import timezone
from datetime import timezone as dt_timezone

from modules.literature_stream.models.literature import Literature
from modules.journals.models.journal import JournalArticle

logger = logging.getLogger(__name__)


class DataLoader:
    """数据加载器"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def load_literature_data(
        self,
        window: str,
        as_of: datetime
    ) -> List[Dict]:
        """
        加载文献流数据
        
        Args:
            window: 时间窗口 (1d|7d|30d|180d)
            as_of: 截止日期
            
        Returns:
            文献列表，每项包含: pmid, title, abstract, embedding, mesh_terms, pub_date
        """
        # 计算时间窗口起始日期
        window_days = {"1d": 1, "7d": 7, "30d": 30, "180d": 180}
        days = window_days.get(window, 7)
        start_date = as_of - timedelta(days=days)

        # 1d 窗口：与前端“今日上新”语义对齐，使用 created_at（入库时间）而不是发表日期。
        # 注意：literature.created_at 为 timestamp without time zone，写入口径按 UTC naive 处理。
        use_created_at = window == "1d"
        if use_created_at:
            # as_of 以业务时区传入（Asia/Shanghai），这里按“本地当日 00:00 起”的口径取数
            try:
                local_tz = timezone(timedelta(hours=8))
                as_of_local = as_of.astimezone(local_tz) if as_of.tzinfo else as_of.replace(tzinfo=local_tz)
                start_local = as_of_local.replace(hour=0, minute=0, second=0, microsecond=0)
                start_dt = start_local.astimezone(timezone.utc).replace(tzinfo=None)
                end_dt = as_of_local.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                # 保守回退：使用 UTC naive 的过去24h滑窗
                end_dt = as_of.astimezone(timezone.utc).replace(tzinfo=None) if as_of.tzinfo else as_of
                start_dt = end_dt - timedelta(days=1)

            query = (
                select(Literature)
                .options(
                    load_only(
                        Literature.pmid,
                        Literature.doi,
                        Literature.title,
                        Literature.abstract,
                        Literature.keywords_json,
                        Literature.publication_date,
                        Literature.created_at,
                    )
                )
                .where(
                    and_(
                        Literature.is_deleted == False,
                        Literature.created_at >= start_dt,
                        Literature.created_at <= end_dt,
                    )
                )
                .order_by(Literature.created_at.desc())
            )
        else:
            # 查询literature表（列裁剪 + 流式迭代，避免一次性取回大字段）
            query = (
                select(Literature)
                .options(
                    load_only(
                        Literature.pmid,
                        Literature.doi,
                        Literature.title,
                        Literature.abstract,
                        Literature.keywords_json,
                        Literature.publication_date,
                    )
                )
                .where(
                    and_(
                        Literature.is_deleted == False,
                        Literature.publication_date >= start_date.date(),
                        Literature.publication_date <= as_of.date(),
                    )
                )
                .order_by(Literature.publication_date.desc())
            )

        result = await self.db.stream(query)
        # 转换为字典格式（流式迭代，降低内存峰值）
        data = []
        async for lit in result.scalars():
            # 读取keywords_json（JSONB字段）
            keywords_json = lit.keywords_json if lit.keywords_json else []

            data.append({
                "pmid": lit.pmid,
                "doi": lit.doi,
                "title": lit.title,
                "abstract": lit.abstract or "",
                "keywords_json": keywords_json,
                "pub_date": lit.publication_date.isoformat() if lit.publication_date else None,
                "source": "literature",
            })

        if use_created_at:
            logger.info(
                f"Loaded {len(data)} literature items (window={window}, created_at>={start_dt} <= {end_dt})"
            )
        else:
            logger.info(f"Loaded {len(data)} literature items (window={window}, as_of={as_of.date()})")
        return data
    
    async def load_sports_journals_data(
        self,
        window: str,
        as_of: datetime
    ) -> List[Dict]:
        """加载运动科学期刊数据"""
        return await self._load_journal_data(window, as_of, category="sports_science")
    
    async def load_cns_data(
        self,
        window: str,
        as_of: datetime
    ) -> List[Dict]:
        """加载CNS期刊数据"""
        return await self._load_journal_data(window, as_of, category="cns")
    
    async def _load_journal_data(
        self,
        window: str,
        as_of: datetime,
        category: str
    ) -> List[Dict]:
        """
        加载期刊文章数据（内部方法）
        
        Args:
            window: 时间窗口
            as_of: 截止日期
            category: 分类 (sports_science|cns)
        """
        # 计算时间窗口
        window_days = {"1d": 1, "7d": 7, "30d": 30, "180d": 180}
        days = window_days.get(window, 7)
        start_dt = as_of - timedelta(days=days)

        # 1d 窗口：对“顶刊动向/综合顶刊”而言，用户语义是“今日上新”，
        # 需要覆盖“今日抓取带来的新增 + 字段更新”，而不是发表日期。
        # 与模块2的 window=updated_today 口径一致，这里使用 updated_at（本地当日 00:00 起）。
        use_updated_at = window == "1d"

        # 兼容 naive datetime（默认按 UTC 解释）与 tz-aware datetime
        def _coerce_dt(dt: datetime) -> datetime:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        if use_updated_at:
            try:
                # as_of 由 snapshot task 以 Asia/Shanghai 传入；此处按本地日期的 00:00~as_of 取数
                local_tz = dt_timezone(timedelta(hours=8))
                as_of_local = as_of.astimezone(local_tz) if as_of.tzinfo else as_of.replace(tzinfo=local_tz)
                start_local = as_of_local.replace(hour=0, minute=0, second=0, microsecond=0)
                start_dt = start_local.astimezone(dt_timezone.utc)
                end_dt = as_of_local.astimezone(dt_timezone.utc)
            except Exception:
                end_dt = _coerce_dt(as_of)
                start_dt = end_dt - timedelta(days=1)
        else:
            start_date = start_dt.date()
            end_date = as_of.date()
        
        # 查询journal_articles表（列裁剪 + 流式迭代）
        if use_updated_at:
            query = (
                select(JournalArticle)
                .options(
                    load_only(
                        JournalArticle.pmid,
                        JournalArticle.doi,
                        JournalArticle.title,
                        JournalArticle.abstract,
                        JournalArticle.keywords_json,
                        JournalArticle.publication_date,
                        JournalArticle.category,
                        JournalArticle.created_at,
                        JournalArticle.updated_at,
                    )
                )
                .where(
                    and_(
                        JournalArticle.category == category,
                        JournalArticle.updated_at >= start_dt,
                        JournalArticle.updated_at <= end_dt,
                    )
                )
                .order_by(JournalArticle.updated_at.desc())
            )
        else:
            query = (
                select(JournalArticle)
                .options(
                    load_only(
                        JournalArticle.pmid,
                        JournalArticle.doi,
                        JournalArticle.title,
                        JournalArticle.abstract,
                        JournalArticle.keywords_json,
                        JournalArticle.publication_date,
                        JournalArticle.category,
                        JournalArticle.created_at,
                    )
                )
                .where(
                    and_(
                        JournalArticle.category == category,
                        JournalArticle.publication_date >= start_date,
                        JournalArticle.publication_date <= end_date,
                    )
                )
                .order_by(JournalArticle.publication_date.desc())
            )

        result = await self.db.stream(query)
        # 转换为字典格式（流式迭代）
        data = []
        async for article in result.scalars():
            # 读取keywords_json（JSONB字段）
            keywords_json = article.keywords_json if article.keywords_json else []

            data.append({
                "pmid": article.pmid or f"doi:{article.doi}",  # 使用PMID或DOI作为ID
                "doi": article.doi,
                "title": article.title,
                "abstract": article.abstract or "",
                "keywords_json": keywords_json,
                "pub_date": article.publication_date.isoformat() if article.publication_date else None,
                "created_at": article.created_at.isoformat() if getattr(article, "created_at", None) else None,
                "source": category,
            })

        if use_updated_at:
            logger.info(
                f"Loaded {len(data)} {category} journal articles (window={window}, updated_at>={start_dt.isoformat()} <= {end_dt.isoformat()})"
            )
        else:
            logger.info(f"Loaded {len(data)} {category} journal articles (window={window}, as_of={as_of.date()})")
        return data
