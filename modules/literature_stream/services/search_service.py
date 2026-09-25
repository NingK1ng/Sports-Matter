"""
Literature Search Service
与模块2（journals）检索策略对齐：preprocess/build_tsquery
任务0.1: 添加完整的search方法，从routes.py抽取查询逻辑
"""
import re
from datetime import datetime, timedelta
from typing import Tuple, Optional, List
from sqlalchemy import select, func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.literature_stream.models.literature import Literature
from modules.literature_stream.config.loader import ConfigLoader
from core.search_query import pubmed_tiab_to_tsquery


class LiteratureSearchService:
    def __init__(self, session: AsyncSession | None = None):
        self.session = session
        from pathlib import Path
        config_dir = Path(__file__).parent.parent / "config"
        self.config_loader = ConfigLoader(config_dir=str(config_dir))
    
    def preprocess_query(self, keywords: str) -> str:
        """
        查询预处理（PubMed-like tiab）
        - 保留括号/引号/*/[tiab] 等语法字符
        - 仅规整空白与控制字符
        """
        if not keywords:
            return ""
        cleaned = re.sub(r"[\u0000-\u001f]+", " ", keywords)
        return re.sub(r"\s+", " ", cleaned).strip()

    def build_tsquery(self, keywords: str) -> Tuple[str, dict]:
        """
        返回 (tsquery_sql_snippet, params)：
        - 使用 PubMed-like 语法编译为 tsquery 字符串，然后统一走 to_tsquery
        """
        if not keywords:
            return "", {}
        cleaned = self.preprocess_query(keywords)
        tsquery = pubmed_tiab_to_tsquery(cleaned)
        return "to_tsquery('english', unaccent(:kw))", {"kw": tsquery}

    async def search(
        self,
        keywords: Optional[str] = None,
        search_scope: str = "tiab",
        categories: Optional[List[str]] = None,
        lit_types: Optional[List[str]] = None,
        top_journals: bool = False,
        filter_quality: bool = False,
        window: Optional[str] = None,
        sort_by: str = "date",
        limit: int = 20,
        offset: int = 0
    ) -> Tuple[List[Literature], int]:
        """
        统一的文献检索方法（从routes.py迁移）
        返回：(文献列表, 总数) - 与模块2 SearchService.search_articles 对齐
        
        Args:
            keywords: 关键词
            search_scope: 搜索范围 ti|tiab
            categories: 学科类别列表
            lit_types: 文献类型列表
            top_journals: 是否仅5本顶刊
            filter_quality: 是否启用黑名单过滤
            window: 时间窗口（如30d, 7d, 1d）或绝对日期（YYYY-MM-DD）
            sort_by: 排序方式 date|if|if5|relevance
            limit: 每页数量
            offset: 偏移量
        
        Returns:
            (文献列表, 总数)
        """
        if self.session is None:
            raise RuntimeError("LiteratureSearchService.search() requires an AsyncSession")
        # 构建基础查询
        query = select(Literature).where(Literature.is_deleted == False)
        count_query = select(func.count()).select_from(Literature).where(Literature.is_deleted == False)
        
        # 分类过滤（支持多选）
        if categories:
            query = query.where(
                or_(*[Literature.subject_categories.contains([cat]) for cat in categories])
            )
            count_query = count_query.where(
                or_(*[Literature.subject_categories.contains([cat]) for cat in categories])
            )
        
        # 文献类型过滤（支持多选）
        if lit_types:
            # 展开"original"为2个子类
            expanded_types = []
            for t in lit_types:
                if t == 'original':
                    expanded_types.extend(['original_human', 'original_animal'])
                else:
                    expanded_types.append(t)
            
            query = query.where(
                or_(*[Literature.literature_types.contains([t]) for t in expanded_types])
            )
            count_query = count_query.where(
                or_(*[Literature.literature_types.contains([t]) for t in expanded_types])
            )
        
        # 时间窗口过滤
        if window:
            if window.endswith('d'):
                # 相对窗口（如30d）—— 过去N天（不包含今天）
                days = int(window[:-1])
                if days <= 0:
                    days = 1
                start = datetime.now().date() - timedelta(days=days)
                query = query.where(Literature.publication_date >= start)
                count_query = count_query.where(Literature.publication_date >= start)
            else:
                # 绝对日期（如2024-01-01）
                try:
                    start = datetime.strptime(window, '%Y-%m-%d').date()
                    query = query.where(Literature.publication_date >= start)
                    count_query = count_query.where(Literature.publication_date >= start)
                except:
                    pass
        
        # 关键词搜索（全文检索）
        rank_selected = False
        rank_alias = None
        if keywords:
            cleaned = self.preprocess_query(keywords)
            if cleaned:
                tsquery, params = self.build_tsquery(cleaned)
                if search_scope == 'ti':
                    search_condition = text(f"title_vector @@ {tsquery}")
                    rank_expr = text(f"ts_rank(title_vector, {tsquery}) AS rank")
                else:
                    search_condition = text(f"(title_vector || abstract_vector) @@ {tsquery}")
                    rank_expr = text(f"ts_rank(title_vector || abstract_vector, {tsquery}) AS rank")

                query = query.where(search_condition).params(**params)
                count_query = count_query.where(search_condition).params(**params)

                if sort_by == 'relevance':
                    query = query.add_columns(rank_expr).params(**params)
                    rank_selected = True
                    rank_alias = 'rank'
        
        # 期刊过滤
        if top_journals:
            # guideline类型不适用顶刊过滤
            selected_types = set(lit_types) if lit_types else set()
            if 'guideline' not in selected_types:
                top_issns = self.config_loader.load_journal_filters()['top_journals']
                query = query.where(Literature.journal_issn.in_(top_issns))
                count_query = count_query.where(Literature.journal_issn.in_(top_issns))
        
        if filter_quality:
            # 只排除明确在黑名单内的ISSN
            blacklist_issns = self.config_loader.load_journal_filters()['blacklist']
            query = query.where(
                or_(
                    Literature.journal_issn.is_(None),
                    ~Literature.journal_issn.in_(blacklist_issns)
                )
            )
            count_query = count_query.where(
                or_(
                    Literature.journal_issn.is_(None),
                    ~Literature.journal_issn.in_(blacklist_issns)
                )
            )

        # 仅限中科院一区期刊（CAS 1区）
        # 前端通过 only_zone1 参数触发
        # 注意：为了保持接口兼容，这里通过 sort_by 的扩展参数传递
        if sort_by == 'zone1_only':
            query = query.where(Literature.journal_zone.ilike('%1区%'))
            count_query = count_query.where(Literature.journal_zone.ilike('%1区%'))
        
        # 排序
        if sort_by == 'relevance' and keywords:
            query = query.order_by(text("rank DESC"), Literature.publication_date.desc())
        elif sort_by in ['if', 'if5']:
            # 按5年IF排序（缺失时用CiteScore）
            query = query.order_by(
                func.coalesce(Literature.journal_if_5y, Literature.journal_citescore, 0).desc(),
                Literature.publication_date.desc()
            )
        else:
            # 默认按日期排序
            query = query.order_by(Literature.publication_date.desc())
        
        # 计算总数
        total_result = await self.session.execute(count_query)
        total = total_result.scalar()
        
        # 分页
        query = query.offset(offset).limit(limit)
        
        # 执行查询
        result = await self.session.execute(query)
        if rank_selected:
            rows = result.fetchall()
            items = []
            for row in rows:
                lit_obj = row[0]
                rank_val = None
                try:
                    rank_val = row[1]
                except Exception:
                    try:
                        rank_val = getattr(row, rank_alias)
                    except Exception:
                        rank_val = None
                setattr(lit_obj, 'rank', float(rank_val) if rank_val is not None else None)
                items.append(lit_obj)
        else:
            items = result.scalars().all()
        
        return items, total












