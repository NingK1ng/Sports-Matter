"""
文献流模块API路由
实现所有10个API端点
"""
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Response
from sqlalchemy import select, func, text, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
import pytz

from core.database import get_db
from core.config import settings
from modules.literature_stream.api.schemas import (
    CategoryResponse,
    LiteratureResponse,
    LiteratureListResponse,
    JournalResponse,
    QueryResponse,
    CrawlStatsResponse,
)
from modules.literature_stream.models.literature import (
    SubjectCategoryConfig,
    Literature,
    JournalMetadata,
    CrawlTaskLog,
)
from modules.literature_stream.config.filters import JournalFilter
from modules.literature_stream.config.loader import ConfigLoader
from modules.literature_stream.services.search_service import LiteratureSearchService
from core.search_query import QueryParseError
from pathlib import Path

router = APIRouter(prefix="/stream", tags=["literature-stream"])

# 配置加载器
config_dir = Path(__file__).parent.parent.parent.parent / "config" / "literature-stream"
config_loader = ConfigLoader(config_dir)
journal_filter = JournalFilter(config_loader)


# 3.1 GET /v1/stream/categories - 获取分类列表
@router.get("/categories", response_model=List[CategoryResponse])
async def get_categories(
    enabled_only: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """获取学科分类列表（包含每个分类的PubMed检索式）"""
    query = select(SubjectCategoryConfig).order_by(SubjectCategoryConfig.display_order)
    
    if enabled_only:
        query = query.where(SubjectCategoryConfig.is_enabled == True)
    
    result = await db.execute(query)
    categories = result.scalars().all()

    # 动态统计每个分类的文献数（避免doc_count为0的初始值误导）
    for cat in categories:
        count_result = await db.execute(
            select(func.count())
            .select_from(Literature)
            .where(
                Literature.subject_categories.contains([cat.category_key]),
                Literature.is_deleted == False
            )
        )
        # 直接覆盖返回值，不提交数据库
        try:
            cat.doc_count = int(count_result.scalar() or 0)
        except Exception:
            pass

    return categories


# 3.9 GET /v1/stream/categories/{category_key}/query - 获取检索式
@router.get("/categories/{category_key}/query", response_model=QueryResponse)
async def get_category_query(
    category_key: str,
    db: AsyncSession = Depends(get_db)
):
    """获取指定学科类的完整PubMed检索式"""
    result = await db.execute(
        select(SubjectCategoryConfig).where(
            SubjectCategoryConfig.category_key == category_key
        )
    )
    category = result.scalar_one_or_none()
    
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    
    return QueryResponse(
        category_key=category.category_key,
        display_name=category.display_name,
        pubmed_query=category.pubmed_query
    )


# 3.2 GET /v1/stream/literature - 分页检索文献
@router.get("/literature", response_model=LiteratureListResponse)
async def get_literature(
    # 分页参数
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(20, ge=1, le=100, description="每页数量"),
    
    # 分类过滤
    category: Optional[str] = Query(None, description="学科类别key"),
    categories: Optional[str] = Query(None, description="多个学科类（逗号分隔）"),
    lit_type: Optional[str] = Query(None, description="文献类型"),
    lit_types: Optional[str] = Query(None, description="多个文献类型（逗号分隔）"),
    
    # 时间窗口
    window: Optional[str] = Query(None, description="时间窗口（如30d, 7d, 1d）或绝对日期（YYYY-MM-DD）"),
    start_date: Optional[str] = Query(None, description="开始日期（YYYY-MM-DD）"),
    end_date: Optional[str] = Query(None, description="结束日期（YYYY-MM-DD）"),
    
    # 关键词搜索
    keywords: Optional[str] = Query(None, description="关键词搜索"),
    search_scope: str = Query("tiab", description="搜索范围: ti|tiab"),
    
    # 期刊过滤
    top_journals: bool = Query(False, description="仅5本顶刊"),
    journal_issn: Optional[str] = Query(None, description="期刊ISSN过滤（精确匹配，支持逗号分隔）"),
    # filter_quality：过滤中科院四区期刊（保留1-3区及未知分区）
    filter_quality: bool = Query(False, description="过滤中科院四区期刊"),
    # 仅中科院一区期刊
    only_zone1: bool = Query(False, description="仅中科院一区期刊"),
    # 分区多选过滤（如 '1,2,3'）
    zones: Optional[str] = Query(None, description="中科院分区多选，如 '1,2,3'"),
    
    # 排序
    sort_by: str = Query("date", description="排序方式: date|if|if5|relevance"),
    
    db: AsyncSession = Depends(get_db),
    response: Response = None,
):
    """
    分页检索文献
    支持分类过滤、关键词搜索、时间窗口、期刊过滤、排序
    """
    # 构建基础查询
    query = select(Literature).where(Literature.is_deleted == False)
    count_query = select(func.count()).select_from(Literature).where(Literature.is_deleted == False)

    # 默认规则：隐藏明确标记为 non_research 的文献（除非用户显式按类型筛选）
    if not lit_type and not lit_types:
        query = query.where(
            or_(
                Literature.literature_types.is_(None),
                ~Literature.literature_types.contains(["non_research"]),
            )
        )
        count_query = count_query.where(
            or_(
                Literature.literature_types.is_(None),
                ~Literature.literature_types.contains(["non_research"]),
            )
        )
    
    # 分类过滤（支持多选）
    if categories:
        cat_list = [c.strip() for c in categories.split(',')]
        query = query.where(
            or_(*[Literature.subject_categories.contains([cat]) for cat in cat_list])
        )
        count_query = count_query.where(
            or_(*[Literature.subject_categories.contains([cat]) for cat in cat_list])
        )
    elif category:
        query = query.where(Literature.subject_categories.contains([category]))
        count_query = count_query.where(Literature.subject_categories.contains([category]))
    
    # 文献类型过滤（支持多选）
    if lit_types:
        type_list = [t.strip() for t in lit_types.split(',')]
        # 展开"original"为3个子类
        expanded_types = []
        for t in type_list:
            if t == 'original':
                expanded_types.extend(['original_human', 'original_animal'])  # 简化为2个子类
            else:
                expanded_types.append(t)
        
        query = query.where(
            or_(*[Literature.literature_types.contains([t]) for t in expanded_types])
        )
        count_query = count_query.where(
            or_(*[Literature.literature_types.contains([t]) for t in expanded_types])
        )
    elif lit_type:
        # 展开"original"为2个子类
        if lit_type == 'original':
            query = query.where(
                or_(
                    Literature.literature_types.contains(['original_human']),
                    Literature.literature_types.contains(['original_animal'])
                )
            )
            count_query = count_query.where(
                or_(
                    Literature.literature_types.contains(['original_human']),
                    Literature.literature_types.contains(['original_animal'])
                )
            )
        else:
            query = query.where(Literature.literature_types.contains([lit_type]))
            count_query = count_query.where(Literature.literature_types.contains([lit_type]))
    
    # 时间窗口过滤
    if window:
        tz = pytz.timezone(getattr(settings, "timezone", "Asia/Shanghai"))
        now_local = datetime.now(tz)
        if window == "today":
            # 今日上新：按创建时间过滤今日入库的文献，避免未来出版日期顶在最前
            start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            # created_at 为 timestamp without time zone，写入口径为 UTC（naive）
            start_dt = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
            query = query.where(Literature.created_at >= start_dt)
            count_query = count_query.where(Literature.created_at >= start_dt)
        elif window.endswith('d'):
            # 相对窗口（如30d）—— 过去N天（不包含今天）
            days = int(window[:-1])
            if days <= 0:
                days = 1
            start = now_local.date() - timedelta(days=days)
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
    elif start_date or end_date:
        if start_date:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.where(Literature.publication_date >= start)
            count_query = count_query.where(Literature.publication_date >= start)
        if end_date:
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.where(Literature.publication_date <= end)
            count_query = count_query.where(Literature.publication_date <= end)
    
    # 关键词搜索（全文检索）
    rank_selected = False
    rank_alias = None
    if keywords:
        svc = LiteratureSearchService()
        try:
            tsquery, params = svc.build_tsquery(keywords)
        except QueryParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if tsquery:
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

    # 期刊过滤（按ISSN精确匹配，支持逗号分隔）
    if journal_issn:
        issns = [x.strip() for x in journal_issn.split(",") if x and x.strip()]
        if issns:
            query = query.where(Literature.journal_issn.in_(issns))
            count_query = count_query.where(Literature.journal_issn.in_(issns))
    
    # 期刊过滤
    if top_journals:
        # guideline类型不适用顶刊过滤：忽略并设置警告响应头
        selected_types = set()
        if lit_type:
            selected_types.add(lit_type)
        if lit_types:
            selected_types.update(t.strip() for t in lit_types.split(',') if t.strip())
        if 'guideline' in selected_types:
            if response is not None:
                response.headers['X-Warning'] = 'Top journals filter is not applicable for guidelines/consensus/protocol'
        else:
            top_issns = config_loader.load_journal_filters()['top_journals']
            query = query.where(Literature.journal_issn.in_(top_issns))
            count_query = count_query.where(Literature.journal_issn.in_(top_issns))
    
    if filter_quality:
        # 使用已回填到 Literature.journal_zone 的中科院分区，过滤掉四区期刊
        # 保留：1区/2区/3区，以及尚未有分区信息的期刊
        query = query.where(
            or_(
                Literature.journal_zone.is_(None),
                and_(
                    Literature.journal_zone.is_not(None),
                    func.upper(Literature.journal_zone) != 'Q4',
                    ~Literature.journal_zone.like('%4区%')
                )
            )
        )
    
    # 仅限中科院一区期刊/Q1期刊
    if only_zone1:
        query = query.where(
            or_(
                Literature.journal_zone == 'Q1',
                Literature.journal_zone.ilike('%1区%')
            )
        )
        count_query = count_query.where(
            or_(
                Literature.journal_zone == 'Q1',
                Literature.journal_zone.ilike('%1区%')
            )
        )

    # 分区多选过滤（1-4区）
    if zones:
        selected = [z.strip() for z in zones.split(',') if z.strip()]
        if selected:
            zone_values: list[str] = []
            for z in selected:
                if z in ('1', '1区', 'Q1'):
                    zone_values.extend(['Q1', '1区'])
                elif z in ('2', '2区', 'Q2'):
                    zone_values.extend(['Q2', '2区'])
                elif z in ('3', '3区', 'Q3'):
                    zone_values.extend(['Q3', '3区'])
                elif z in ('4', '4区', 'Q4'):
                    zone_values.extend(['Q4', '4区'])
            zone_values = list({v for v in zone_values})
            if zone_values:
                query = query.where(Literature.journal_zone.in_(zone_values))
                count_query = count_query.where(Literature.journal_zone.in_(zone_values))
    
    # 排序
    if sort_by == 'relevance' and keywords:
        query = query.order_by(
            text("rank DESC"),
            Literature.publication_date.desc().nullslast(),
        )
    elif sort_by in ['if', 'if5']:
        # 按5年IF排序（缺失时用CiteScore）
        query = query.order_by(
            func.coalesce(Literature.journal_if_5y, Literature.journal_citescore, 0).desc(),
            Literature.publication_date.desc().nullslast(),
        )
    else:
        # 默认按日期排序
        query = query.order_by(Literature.publication_date.desc().nullslast())
    
    # 计算总数
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # 分页
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    
    # 执行查询
    result = await db.execute(query)
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
    
    # 计算总页数
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    
    return LiteratureListResponse(
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        items=items
    )


# 3.11 GET /v1/stream/journals - 获取期刊列表
@router.get("/journals", response_model=List[JournalResponse])
async def get_journals(
    top_only: bool = Query(False, description="仅顶刊"),
    exclude_blacklist: bool = Query(False, description="排除黑名单"),
    db: AsyncSession = Depends(get_db)
):
    """获取期刊列表（用于调试和期刊信息展示）"""
    query = select(JournalMetadata).order_by(
        JournalMetadata.if_5y.desc().nullslast()
    )
    
    if top_only:
        query = query.where(JournalMetadata.is_top_journal == True)
    
    if exclude_blacklist:
        query = query.where(JournalMetadata.is_blacklisted == False)
    
    result = await db.execute(query)
    journals = result.scalars().all()
    
    return journals


# 额外端点：获取统计信息
@router.get("/stats", response_model=CrawlStatsResponse)
async def get_stats(
    window: Optional[str] = Query(None, description="时间窗口（如30d, 7d, 1d）或绝对日期（YYYY-MM-DD）"),
    db: AsyncSession = Depends(get_db),
):
    """获取爬取统计信息（可选时间窗口）"""
    # 解析时间窗口
    start_filter = None
    if window:
        try:
            tz = pytz.timezone(getattr(settings, "timezone", "Asia/Shanghai"))
            now_local = datetime.now(tz)
            if window == "today":
                start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
                # created_at 为 timestamp without time zone，写入口径为 UTC（naive）
                start_filter = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
            elif window.endswith('d'):
                days = int(window[:-1])
                if days <= 0:
                    days = 1
                start_filter = (now_local.date() - timedelta(days=days))
            else:
                start_filter = datetime.strptime(window, '%Y-%m-%d').date()
        except Exception:
            start_filter = None
    else:
        # 默认自 2024-01-01 起
        start_filter = datetime.strptime('2024-01-01', '%Y-%m-%d').date()

    base_where = [Literature.is_deleted == False]
    if start_filter:
        # 今日上新按创建时间，其它窗口按 publication_date
        if window == "today":
            base_where.append(Literature.created_at >= start_filter)
        else:
            base_where.append(Literature.publication_date >= start_filter)

    # 总文献数（按窗口）
    total_result = await db.execute(
        select(func.count()).select_from(Literature).where(*base_where)
    )
    total = total_result.scalar()
    
    # 按学科类统计
    by_category = {}
    categories_result = await db.execute(select(SubjectCategoryConfig))
    categories = categories_result.scalars().all()
    
    for cat in categories:
        where_clause = [
            Literature.subject_categories.contains([cat.category_key]),
            Literature.is_deleted == False,
        ]
        if start_filter:
            where_clause.append(Literature.publication_date >= start_filter)
        count_result = await db.execute(
            select(func.count()).select_from(Literature).where(*where_clause)
        )
        by_category[cat.display_name] = count_result.scalar()
    
    # 按文献类型统计
    by_type = {}
    for lit_type in ['meta_analysis', 'original_human', 'original_animal', 'review', 'guideline']:
        where_clause = [
            Literature.literature_types.contains([lit_type]),
            Literature.is_deleted == False,
        ]
        if start_filter:
            where_clause.append(Literature.publication_date >= start_filter)
        count_result = await db.execute(
            select(func.count()).select_from(Literature).where(*where_clause)
        )
        by_type[lit_type] = count_result.scalar()
    
    # 最后爬取时间
    last_crawl_result = await db.execute(
        select(CrawlTaskLog.finished_at)
        .where(CrawlTaskLog.status == 'success')
        .order_by(CrawlTaskLog.finished_at.desc())
        .limit(1)
    )
    last_crawl = last_crawl_result.scalar_one_or_none()
    
    return CrawlStatsResponse(
        total_literature=total,
        by_category=by_category,
        by_type=by_type,
        last_crawl=last_crawl
    )
