"""
顶刊追踪模块API路由
任务6.2-6.3: 实现所有API端点
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.journals.api.schemas import (
    JournalResponse,
    ArticleResponse,
    ArticleListResponse,
    StatsResponse,
)
from modules.journals.models.journal import JournalMetadata, JournalArticle, CrawlTaskLog
from modules.journals.services.search_service import SearchService
from core.search_query import QueryParseError

router = APIRouter(prefix="/journals", tags=["journals-tracking"])


async def _resolve_issn_to_issn_l(db: AsyncSession, issns: list[str]) -> list[str]:
    """将任意ISSN（print/electronic/ISSN-L）归一化为ISSN-L列表"""
    if not issns:
        return []
    # 去重/清洗
    norm = list({i.strip() for i in issns if i and i.strip()})
    if not norm:
        return []
    stmt = (
        select(JournalMetadata.issn_l)
        .where(
            (JournalMetadata.issn_l.in_(norm))
            | (JournalMetadata.issn_print.in_(norm))
            | (JournalMetadata.issn_electronic.in_(norm))
        )
    )
    res = await db.execute(stmt)
    return [row[0] for row in res.fetchall()]


@router.get("/list", response_model=List[JournalResponse])
async def get_journals(
    category: Optional[str] = Query(None, description="期刊分类：sports_science|cns"),
    db: AsyncSession = Depends(get_db),
):
    """
    获取期刊列表
    任务6.2
    """
    query = select(JournalMetadata).order_by(JournalMetadata.estimated_if.desc().nullslast())
    
    if category:
        query = query.where(JournalMetadata.category == category)
    
    result = await db.execute(query)
    journals = result.scalars().all()
    
    return journals


@router.get("/articles", response_model=ArticleListResponse)
async def get_articles(
    # 关键词搜索
    keywords: Optional[str] = Query(None, description="关键词（支持布尔运算符）"),
    search_scope: str = Query("tiab", description="搜索范围：ti（仅标题）|tiab（标题+摘要）"),
    
    # 分类和期刊过滤
    category: Optional[str] = Query(None, description="期刊分类：sports_science|cns"),
    issn: Optional[str] = Query(None, description="期刊ISSN（逗号分隔，支持多选）"),
    
    # 标签过滤
    labels: Optional[str] = Query(None, description="标签（逗号分隔，OR逻辑）：new,recent,trending,hot,classic"),
    
    # 时间范围
    since: Optional[str] = Query(None, description="起始日期（YYYY-MM-DD）"),
    until: Optional[str] = Query(None, description="结束日期（YYYY-MM-DD）"),
    window: Optional[str] = Query(None, description="时间窗口: today(今日入库) | updated_today(今日更新) | YYYY-MM-DD"),
    
    # 排序和分页
    sort_by: str = Query("date", description="排序方式：relevance|date|citations"),
    page: int = Query(1, ge=1, description="页码"),
    per_page: int = Query(20, ge=1, le=100, description="每页数量"),

    # CNS：运动相关过滤（基于预计算的 LLM 标注）
    sports_only: bool = Query(False, description="仅显示运动相关（仅对 CNS 分类生效）"),
    
    db: AsyncSession = Depends(get_db),
):
    """
    获取文章列表（统一端点）
    任务6.3: 支持关键词搜索、分类过滤、标签过滤、排序
    """
    # 解析ISSN列表（归一化到ISSN-L）
    issn_list = None
    if issn:
        input_list = [i.strip() for i in issn.split(",") if i.strip()]
        issn_list = await _resolve_issn_to_issn_l(db, input_list)
    
    # 解析标签列表
    label_list = None
    if labels:
        label_list = [l.strip() for l in labels.split(",") if l.strip()]
    
    # 创建搜索服务
    search_service = SearchService(db)
    
    # 执行搜索
    try:
        articles, total = await search_service.search_articles(
            keywords=keywords,
            category=category,
            search_scope=search_scope,
            issn_list=issn_list,
            labels=label_list,
            since=since,
            until=until,
            window=window,
            sort_by=sort_by,
            page=page,
            per_page=per_page,
            sports_only=sports_only,
        )
    except QueryParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    
    # 计算总页数
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    
    return ArticleListResponse(
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        items=articles,
    )


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
):
    """
    获取统计信息
    """
    # 总文章数
    total_result = await db.execute(select(func.count()).select_from(JournalArticle))
    total = total_result.scalar()
    
    # 按分类统计
    by_category = {}
    for category in ["sports_science", "cns"]:
        count_result = await db.execute(
            select(func.count())
            .select_from(JournalArticle)
            .where(JournalArticle.category == category)
        )
        by_category[category] = count_result.scalar()
    
    # 按期刊统计
    by_journal = {}
    journal_result = await db.execute(
        select(JournalArticle.journal_issn, func.count())
        .group_by(JournalArticle.journal_issn)
    )
    for issn, count in journal_result:
        by_journal[issn] = count
    
    # 最后爬取时间
    last_crawl_result = await db.execute(
        select(CrawlTaskLog.finished_at)
        .where(CrawlTaskLog.status == "success")
        .order_by(CrawlTaskLog.finished_at.desc())
        .limit(1)
    )
    last_crawl = last_crawl_result.scalar_one_or_none()
    
    return StatsResponse(
        total_articles=total,
        by_category=by_category,
        by_journal=by_journal,
        last_crawl=last_crawl,
    )
