"""
全文检索服务
任务6.1.5: PostgreSQL全文检索实现
"""
import re
from datetime import datetime
from typing import Optional, List, Tuple
from sqlalchemy import text, select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
import logging
import pytz

from modules.journals.models.journal import JournalArticle
from core.config import settings
from core.search_query import pubmed_tiab_to_tsquery

logger = logging.getLogger(__name__)


class SearchService:
    """全文检索服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    def preprocess_query(self, keywords: str) -> str:
        """
        查询预处理
        
        Args:
            keywords: 原始关键词
        
        Returns:
            预处理后的查询字符串
        """
        if not keywords:
            return ""
        # PubMed-like 语法需要保留括号/引号/*/[tiab] 等，尽量不做破坏性清洗。
        # 这里只做空白与控制字符规整，实际解析/校验在 pubmed_tiab_to_tsquery 中完成。
        cleaned = re.sub(r"[\u0000-\u001f]+", " ", keywords)
        return re.sub(r"\s+", " ", cleaned).strip()

    def build_tsquery(self, keywords: str) -> tuple[str, dict]:
        """
        构建PostgreSQL tsquery SQL 片段 + 绑定参数（PubMed-like tiab）
        支持 AND/OR/NOT、括号、短语引号、前缀通配符 *、以及可选 [tiab]。
        """
        if not keywords:
            return "", {}
        cleaned = self.preprocess_query(keywords)
        tsquery = pubmed_tiab_to_tsquery(cleaned)
        return "to_tsquery('english', unaccent(:kw))", {"kw": tsquery}

    async def search_articles(
        self,
        keywords: Optional[str] = None,
        category: Optional[str] = None,
        search_scope: str = "tiab",  # ti|tiab
        issn_list: Optional[List[str]] = None,
        labels: Optional[List[str]] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        window: Optional[str] = None,
        sort_by: str = "date",  # relevance|date|citations
        page: int = 1,
        per_page: int = 20,
        sports_only: bool = False,
    ) -> Tuple[List[JournalArticle], int]:
        """
        搜索文章
        
        Returns:
            (文章列表, 总数)
        """
        # 构建基础查询
        query = select(JournalArticle)
        count_query = select(func.count()).select_from(JournalArticle)
        
        # 分类过滤
        if category:
            query = query.where(JournalArticle.category == category)
            count_query = count_query.where(JournalArticle.category == category)
        
        # 期刊过滤
        if issn_list:
            query = query.where(JournalArticle.journal_issn.in_(issn_list))
            count_query = count_query.where(JournalArticle.journal_issn.in_(issn_list))
        
        # 标签过滤（OR逻辑）
        if labels:
            label_conditions = [JournalArticle.labels.contains([label]) for label in labels]
            query = query.where(or_(*label_conditions))
            count_query = count_query.where(or_(*label_conditions))

        # CNS：运动相关过滤（依赖 extra_metadata 预先写入 sports_related=true）
        if sports_only and category == "cns":
            sports_condition = text("coalesce(extra_metadata ->> 'sports_related', 'false') = 'true'")
            query = query.where(sports_condition)
            count_query = count_query.where(sports_condition)
        
        # 时间范围过滤
        time_filter_mode: Optional[str] = None  # created|updated|None(=pub_date)
        if window == "today":
            tz = pytz.timezone(getattr(settings, "timezone", "Asia/Shanghai"))
            start_dt = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.where(JournalArticle.created_at >= start_dt)
            count_query = count_query.where(JournalArticle.created_at >= start_dt)
            time_filter_mode = "created"
        elif window == "updated_today":
            tz = pytz.timezone(getattr(settings, "timezone", "Asia/Shanghai"))
            start_dt = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
            query = query.where(JournalArticle.updated_at >= start_dt)
            count_query = count_query.where(JournalArticle.updated_at >= start_dt)
            time_filter_mode = "updated"
        else:
            if since:
                since_date = datetime.strptime(since, '%Y-%m-%d').date()
                query = query.where(JournalArticle.publication_date >= since_date)
                count_query = count_query.where(JournalArticle.publication_date >= since_date)
            if until:
                until_date = datetime.strptime(until, '%Y-%m-%d').date()
                query = query.where(JournalArticle.publication_date <= until_date)
                count_query = count_query.where(JournalArticle.publication_date <= until_date)
        
        # 关键词搜索
        params: dict = {}
        if keywords:
            # 预处理
            cleaned = self.preprocess_query(keywords)
            
            if cleaned:
                # 构建tsquery（绑定参数 + unaccent）
                tsquery, params = self.build_tsquery(cleaned)
                
                # 选择搜索范围
                if search_scope == "ti":
                    # 仅标题
                    search_condition = text(f"title_vector @@ {tsquery}")
                else:
                    # 标题+摘要
                    search_condition = text(f"(title_vector || abstract_vector) @@ {tsquery}")
                
                query = query.where(search_condition).params(**params)
                count_query = count_query.where(search_condition).params(**params)
                
                # 添加相关度评分（仅在relevance排序时）
                if sort_by == "relevance":
                    if search_scope == "ti":
                        rank_expr = text(f"ts_rank(title_vector, {tsquery}) AS rank")
                    else:
                        rank_expr = text(f"ts_rank(title_vector || abstract_vector, {tsquery}) AS rank")
                    query = query.add_columns(rank_expr).params(**params)
        
        # 排序
        if sort_by == "relevance" and keywords:
            order_expr = text("rank DESC")
            if time_filter_mode == "created":
                query = query.order_by(order_expr, JournalArticle.created_at.desc())
            elif time_filter_mode == "updated":
                query = query.order_by(order_expr, JournalArticle.updated_at.desc())
            else:
                query = query.order_by(order_expr, JournalArticle.publication_date.desc())
        elif sort_by == "citations":
            if time_filter_mode == "created":
                query = query.order_by(text("cited_by_count DESC NULLS LAST"), JournalArticle.created_at.desc())
            elif time_filter_mode == "updated":
                query = query.order_by(text("cited_by_count DESC NULLS LAST"), JournalArticle.updated_at.desc())
            else:
                query = query.order_by(text("cited_by_count DESC NULLS LAST"), JournalArticle.publication_date.desc())
        else:
            # 默认按“发表日期”排序（与前端“最新发表”一致）
            # 当使用 today/updated_today 过滤时，将 created/updated 作为次级排序，保证稳定性
            if time_filter_mode == "created":
                query = query.order_by(
                    JournalArticle.publication_date.desc(),
                    JournalArticle.created_at.desc(),
                )
            elif time_filter_mode == "updated":
                query = query.order_by(
                    JournalArticle.publication_date.desc(),
                    JournalArticle.updated_at.desc(),
                )
            else:
                query = query.order_by(JournalArticle.publication_date.desc())
        
        # 计算总数
        total_result = await self.session.execute(count_query)
        total = total_result.scalar()
        
        # 分页
        offset = (page - 1) * per_page
        query = query.offset(offset).limit(per_page)
        
        # 执行查询
        result = await self.session.execute(query)
        
        # 处理结果
        if sort_by == "relevance" and keywords:
            # 包含rank字段
            rows = result.all()
            articles = []
            for row in rows:
                article = row[0]
                article.rank = float(row[1]) if len(row) > 1 else None
                articles.append(article)
        else:
            articles = result.scalars().all()
        
        return articles, total
