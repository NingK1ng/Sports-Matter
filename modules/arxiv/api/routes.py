"""
arXiv API路由
"""
import math
from datetime import date, datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
import pytz

from core.config import settings
from core.database import get_db
from modules.arxiv.api.schemas import (
    ArxivArticleResponse,
    ArxivArticleListResponse,
    ArxivCategoryResponse,
    ArxivStatsResponse,
)
from modules.arxiv.services.arxiv_database import ArxivDatabaseService

router = APIRouter(prefix="/arxiv", tags=["arXiv"])


@router.get("/categories", response_model=list[ArxivCategoryResponse])
async def get_categories(db: AsyncSession = Depends(get_db)):
    """
    获取4大运动科学分类列表

    Returns:
        分类列表（含文档数统计）
    """
    service = ArxivDatabaseService(db)
    categories = await service.get_categories()

    # 获取各分类统计
    stats_list = await service.get_category_stats()
    stats_map = {stat["category"]: stat["count"] for stat in stats_list}

    # 组装响应
    response = []
    for category in categories:
        response.append(
            ArxivCategoryResponse(
                category_key=category.category_key,
                display_name=category.display_name,
                description=category.description,
                doc_count=stats_map.get(category.category_key, 0),
            )
        )

    return response


@router.get("/articles", response_model=ArxivArticleListResponse)
async def get_articles(
    category: Optional[str] = Query(None, description="分类过滤（当前已弱化，可忽略）"),
    keywords: Optional[str] = Query(None, description="关键词搜索"),
    search_scope: str = Query("tiab", description="搜索范围: ti|tiab"),
    source: Optional[str] = Query(None, description="来源: arxiv|biorxiv"),
    window: Optional[str] = Query(None, description="时间窗口: today(今日入库)"),
    date_from: Optional[date] = Query(None, description="起始日期"),
    date_to: Optional[date] = Query(None, description="结束日期"),
    days: Optional[int] = Query(None, description="最近N天", ge=1),
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db),
):
    """
    分页查询文章列表

    Args:
        category: 运动科学分类过滤
        keywords: 关键词搜索（标题+摘要）
        date_from: 起始日期
        date_to: 结束日期
        days: 最近N天（优先级低于date_from/date_to）
        page: 页码
        per_page: 每页数量

    Returns:
        文章列表及分页信息
    """
    service = ArxivDatabaseService(db)

    created_since = None
    created_until = None

    # window 优先级最高：today 表示“按入库时间”的今日
    if window == "today":
        tz = pytz.timezone(getattr(settings, "timezone", "Asia/Shanghai"))
        start_local = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        created_since = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        # “今日入库”口径下，忽略 submitted_date 的 days/date_from/date_to
        date_from = None
        date_to = None
        days = None

    # 处理days参数
    if days and not date_from:
        date_from = (datetime.utcnow() - timedelta(days=days)).date()

    # 查询文章
    articles, total = await service.get_articles(
        category=category,
        keywords=keywords,
        search_scope=search_scope,
        source=source,
        date_from=date_from,
        date_to=date_to,
        created_since=created_since,
        created_until=created_until,
        page=page,
        per_page=per_page,
    )

    # 计算总页数
    pages = math.ceil(total / per_page) if total > 0 else 0

    # 组装响应
    items = [ArxivArticleResponse.model_validate(article) for article in articles]

    return ArxivArticleListResponse(
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        items=items,
    )


@router.get("/articles/{arxiv_id}", response_model=ArxivArticleResponse)
async def get_article_detail(arxiv_id: str, db: AsyncSession = Depends(get_db)):
    """
    获取单篇文章详情

    Args:
        arxiv_id: arXiv ID（如2401.12345）

    Returns:
        文章详情
    """
    service = ArxivDatabaseService(db)
    article = await service.get_article_by_arxiv_id(arxiv_id)

    if not article:
        raise HTTPException(status_code=404, detail="文章未找到")

    return ArxivArticleResponse.model_validate(article)


@router.get("/stats", response_model=ArxivStatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)):
    """
    获取统计数据

    Returns:
        总文章数、各分类文章数
    """
    service = ArxivDatabaseService(db)

    # 总文章数
    total = await service.get_total_count()

    # 各分类统计
    stats_list = await service.get_category_stats()
    category_counts = {stat["category"]: stat["count"] for stat in stats_list}

    return ArxivStatsResponse(
        total_articles=total,
        category_counts=category_counts,
    )
