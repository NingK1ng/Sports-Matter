"""
Celery爬虫任务
统一使用 LLMPubMedCrawler，保证冷启动与热更新逻辑一致
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from celery import shared_task
from dateutil import parser as date_parser
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.task_runtime import run_async
from core.config import settings
from core.cache import init_cache
from core.task_lock import task_lock
from sqlalchemy import select
from modules.literature_stream.models.literature import CrawlTaskLog
from modules.literature_stream.services.llm_crawler import LLMPubMedCrawler


def _build_session_factory():
    # 为避免跨 event loop 复用同一 asyncpg 连接导致
    # “Future attached to a different loop / another operation is in progress”，
    # 每次任务构建独立的 engine / Session 并在任务结束时 dispose 连接池。
    async_engine = create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
        echo=False,
    )
    session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    return async_engine, session_factory


@shared_task(name="literature_stream.daily_incremental_crawl", bind=True, max_retries=3,
             soft_time_limit=1740, time_limit=1800)
def daily_incremental_crawl(self) -> Dict[str, Any]:
    """每日增量爬取任务（UTC+8每日凌晨2点触发）"""
    try:
        with task_lock("literature_daily") as acquired:
            if not acquired:
                return {"status": "already_running"}
            return run_async(_async_daily_crawl())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=min(1800, 120 * 2 ** self.request.retries))


def daily_window(now: datetime, last_end: datetime | None):
    """Resume from the last successful EDAT boundary, with overlap and bounded batches."""
    start = now - timedelta(days=3)
    if last_end:
        if last_end.tzinfo is None:
            last_end = last_end.replace(tzinfo=timezone.utc)
        start = min(start, last_end - timedelta(hours=6))
    return start, min(now, start + timedelta(days=7))


async def _async_daily_crawl() -> Dict[str, Any]:
    """异步执行每日增量爬取"""
    await init_cache()
    engine, SessionLocal = _build_session_factory()
    try:
        async with SessionLocal() as session:
            result = await session.execute(
                select(CrawlTaskLog.query_params)
                .where(CrawlTaskLog.status == "success",
                       CrawlTaskLog.task_type == "incremental_daily")
                .order_by(CrawlTaskLog.started_at.desc()).limit(50)
            )
            ends = []
            for params in result.scalars():
                if params.get("date_field") == "EDAT" and params.get("end_utc"):
                    ends.append(date_parser.parse(params["end_utc"]))
            now = datetime.now(timezone.utc)
            start, end = daily_window(now, max(ends) if ends else None)
            crawler = LLMPubMedCrawler(session)
            result = await crawler.incremental_crawl(start_utc=start, end_utc=end, date_field="EDAT")
            if end < now - timedelta(minutes=1):
                daily_incremental_crawl.apply_async(countdown=60, expires=21600)

            return {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "window_start": start.isoformat(), "window_end": end.isoformat(),
                **result,
            }
    finally:
        await engine.dispose()


@shared_task(name="literature_stream.backfill_last_30d")
def backfill_last_30d() -> Dict[str, Any]:
    """回填最近30天文献（仅写入缺失PMID，已存在会跳过）。"""
    return run_async(_async_backfill_last_days(30))


async def _async_backfill_last_days(days: int) -> Dict[str, Any]:
    """异步执行最近N天回填（使用与每日增量一致的LLMPubMedCrawler管线）。"""
    end_utc = datetime.now(timezone.utc)
    start_utc = end_utc - timedelta(days=days)
    engine, SessionLocal = _build_session_factory()
    try:
        async with SessionLocal() as session:
            crawler = LLMPubMedCrawler(session)
            result = await crawler.incremental_crawl(
                start_utc=start_utc,
                end_utc=end_utc,
                task_type=f"backfill_last_{days}d",
            )
            return {
                "days": days,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                **result,
            }
    finally:
        await engine.dispose()


@shared_task(name="literature_stream.warm_start_all_categories")
def warm_start_all_categories(start_date: str = "2024-01-01") -> Dict[str, Any]:
    """全量回填任务（手动触发或首次部署时执行）"""
    return run_async(_async_warm_start(start_date))


async def _async_warm_start(start_date: str) -> Dict[str, Any]:
    """异步执行全量回填"""
    engine, SessionLocal = _build_session_factory()
    try:
        async with SessionLocal() as session:
            crawler = LLMPubMedCrawler(session)
            result = await crawler.warm_start_crawl(start_date=start_date)

            return {
                "start_date": start_date,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                **result,
            }
    finally:
        await engine.dispose()


@shared_task(name="literature_stream.crawl_single_category")
def crawl_single_category(
    category_key: str,
    start_date: Optional[str] = None,
    incremental: bool = True,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """兼容旧签名的手动触发任务（category_key 参数仅为兼容保留）"""
    return run_async(_async_crawl_single(start_date, end_date, incremental))


async def _async_crawl_single(
    start_date: Optional[str],
    end_date: Optional[str],
    incremental: bool,
) -> Dict[str, Any]:
    """异步执行单次手动爬取"""
    engine, SessionLocal = _build_session_factory()
    try:
        async with SessionLocal() as session:
            crawler = LLMPubMedCrawler(session)

            try:
                if incremental:
                    start_dt = date_parser.parse(start_date) if start_date else None
                    end_dt = date_parser.parse(end_date) if end_date else None
                    result = await crawler.incremental_crawl(
                        start_utc=start_dt,
                        end_utc=end_dt,
                        task_type="incremental_manual",
                    )
                else:
                    result = await crawler.warm_start_crawl(
                        start_date=start_date or "2024-01-01",
                        end_date=end_date,
                    )

                return {
                    "status": "success",
                    "result": result,
                }

            except Exception as exc:
                return {
                    "status": "failed",
                    "error": str(exc),
                }
    finally:
        await engine.dispose()
