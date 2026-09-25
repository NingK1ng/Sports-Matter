"""
Celery爬虫任务
任务5.1-5.2: 定时增量爬取和被引更新
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
from celery import shared_task
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import logging
from sqlalchemy import or_

from core.config import settings
from core.cache import init_cache
from core.celery_app import celery_app
from modules.journals.models.journal import JournalMetadata, JournalArticle, CrawlTaskLog
from modules.journals.services.crawler import JournalCrawler
from modules.journals.services.openalex_client import OpenAlexClient
from modules.journals.services.label_calculator import LabelCalculator

logger = logging.getLogger(__name__)

# 为避免跨 event loop 复用同一 asyncpg 连接导致 “another operation is in progress”，
# 每次任务构建独立的 engine / Session 并在任务结束时 dispose 连接池。
def _build_session_factory():
    async_engine = create_async_engine(
        settings.database_url.replace("postgresql://", "postgresql+asyncpg://"),
        echo=False,
    )
    session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    return async_engine, session_factory


@shared_task(name="journals_tracking.crawl_all_journals")
def crawl_all_journals() -> Dict[str, Any]:
    """
    每日增量爬取任务（拆分派发，避免主任务长时间执行）
    UTC+8每日凌晨4点执行（Celery Beat配置）
    """
    logger.info("开始每日增量爬取...")
    return asyncio.run(_async_crawl_all())


async def _async_crawl_all() -> Dict[str, Any]:
    """异步执行增量爬取"""
    # 将长任务拆分为多个 crawl_single_journal 子任务，避免主任务超时/被清理
    engine, SessionLocal = _build_session_factory()
    dispatched = 0
    batch_size = 10  # 每批派发10个期刊
    delay_between_batches = 30  # 每批间隔30秒
    try:
        async with SessionLocal() as session:
            # 仅用于读取期刊列表
            result = await session.execute(select(JournalMetadata))
            journals = result.scalars().all()

            for i in range(0, len(journals), batch_size):
                batch = journals[i : i + batch_size]
                batch_delay = (i // batch_size) * delay_between_batches
                for j, journal in enumerate(batch):
                    # 在批内再做微小错峰 2 秒
                    countdown = batch_delay + (j * 2)
                    celery_app.send_task(
                        'journals_tracking.crawl_single_journal',
                        args=[journal.issn_l],
                        countdown=countdown,
                        queue='journals_tracking',
                    )
                    dispatched += 1
                    logger.info(
                        f"📨 派发增量爬取任务: {journal.display_name} ({journal.issn_l}), countdown={countdown}s"
                    )

    finally:
        await engine.dispose()

    return {
        "timestamp": datetime.now().isoformat(),
        "dispatched": dispatched,
        "note": "crawls dispatched via crawl_single_journal to avoid long-running task",
    }


@shared_task(name="journals_tracking.rollup_7days")
def rollup_7days() -> Dict[str, Any]:
    """
    7天回补任务（与模块1保持一致）
    每周执行一次，确保没有遗漏
    """
    logger.info("开始7天回补爬取...")
    return asyncio.run(_async_rollup_7days())


async def _async_rollup_7days() -> Dict[str, Any]:
    """异步执行7天回补"""
    engine, SessionLocal = _build_session_factory()
    try:
        async with SessionLocal() as session:
            try:
                await init_cache()
            except Exception:
                pass
            # 获取所有期刊
            result = await session.execute(select(JournalMetadata))
            journals = result.scalars().all()
            
            crawler = JournalCrawler(session)
            results = {}
            
            for journal in journals:
                try:
                    logger.info(f"7天回补: {journal.display_name} ({journal.issn_l})")
                    
                    stats = await crawler.incremental_crawl(
                        issn_l=journal.issn_l,
                        overlap_hours=48,
                        window_days=7,
                        safety_gap_hours=0,
                    )
                    
                    results[journal.issn_l] = {
                        "status": "success",
                        "total": stats["total"],
                        "new": stats["new"],
                        "updated": stats["updated"],
                    }
                    
                    logger.info(f"✅ {journal.display_name}: 7天回补新增{stats['new']}篇")
                
                except Exception as e:
                    results[journal.issn_l] = {
                        "status": "failed",
                        "error": str(e),
                    }
                    logger.error(f"❌ {journal.display_name}: {e}")
            
            await crawler.close()
            
            return {
                "timestamp": datetime.now().isoformat(),
                "results": results,
            }
    finally:
        await engine.dispose()


@shared_task(name="journals_tracking.backfill_last_30d")
def backfill_last_30d() -> Dict[str, Any]:
    """
    回填最近30天（按发表日期 pub-date 扫描，已存在走upsert更新）。

    说明：
    - 采用“派发子任务”模式，与每日增量一致，避免单个任务过长
    - 每个期刊使用 from_date=今天-30天（pub-date），避免“近期入库但发表很久以前”的感知偏差
    """
    logger.info("开始30天回补爬取（派发子任务）...")
    return asyncio.run(_async_dispatch_backfill_last_days(30))


async def _async_dispatch_backfill_last_days(days: int) -> Dict[str, Any]:
    engine, SessionLocal = _build_session_factory()
    dispatched = 0
    batch_size = 10  # 每批派发10个期刊
    delay_between_batches = 30  # 每批间隔30秒
    try:
        async with SessionLocal() as session:
            result = await session.execute(select(JournalMetadata))
            journals = result.scalars().all()

            # Crossref pub-date 使用 YYYY-MM-DD
            from_date = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()

            for i in range(0, len(journals), batch_size):
                batch = journals[i : i + batch_size]
                batch_delay = (i // batch_size) * delay_between_batches
                for j, journal in enumerate(batch):
                    countdown = batch_delay + (j * 2)
                    celery_app.send_task(
                        'journals_tracking.crawl_single_journal',
                        args=[journal.issn_l],
                        kwargs={
                            # 用 cold_start(pub-date) 扫最近N天发表的文章（非 index-date）
                            "cold_start": True,
                            "from_date": from_date,
                        },
                        countdown=countdown,
                        queue='journals_tracking',
                    )
                    dispatched += 1
                    logger.info(
                        f"📨 派发30天回补任务(pub-date): {journal.display_name} ({journal.issn_l}), "
                        f"from_date={from_date}, countdown={countdown}s"
                    )
    finally:
        await engine.dispose()

    return {
        "timestamp": datetime.now().isoformat(),
        "days": days,
        "dispatched": dispatched,
        "note": "backfill dispatched via crawl_single_journal(cold_start=True, pub-date window)",
    }


@shared_task(name="journals_tracking.update_citation_counts")
def update_citation_counts() -> Dict[str, Any]:
    """
    更新被引数和标签
    UTC+8每日凌晨5点执行（Celery Beat配置）
    """
    logger.info("开始更新被引数...")
    return asyncio.run(_async_update_citations())


async def _async_update_citations() -> Dict[str, Any]:
    """异步执行被引更新"""
    engine, SessionLocal = _build_session_factory()
    try:
        async with SessionLocal() as session:
            try:
                await init_cache()
            except Exception:
                pass

            task_log = CrawlTaskLog(
                task_type="citation_update",
                issn_l=None,
                status="running",
                started_at=datetime.now(timezone.utc),
            )
            session.add(task_log)
            await session.commit()
            try:
                # 仅处理需要刷新被引的子集，避免超时
                # 默认：last_citation_update_at 为空或超过7天，最大处理5000篇
                import os
                staleness_days = int(os.getenv("CITATION_STALENESS_DAYS", "7"))
                max_rows = int(os.getenv("CITATION_MAX_ROWS", "5000"))
                cutoff = datetime.now(timezone.utc) - timedelta(days=staleness_days)

                result = await session.execute(
                    select(JournalArticle)
                    .where(
                        or_(
                            JournalArticle.last_citation_update_at.is_(None),
                            JournalArticle.last_citation_update_at < cutoff,
                        )
                    )
                    .order_by(
                        JournalArticle.last_citation_update_at.is_(None).desc(),
                        JournalArticle.last_citation_update_at.asc(),
                        JournalArticle.id.asc(),
                    )
                    .limit(max_rows)
                )
                articles = result.scalars().all()

                if not articles:
                    task_log.status = "success"
                    task_log.total_fetched = 0
                    task_log.updated_count = 0
                    task_log.finished_at = datetime.now(timezone.utc)
                    await session.commit()
                    return {
                        "timestamp": datetime.now().isoformat(),
                        "total_updated": 0,
                        "total_failed": 0,
                        "note": "no stale articles",
                    }

                batch_size = 100
                total_updated = 0
                total_failed = 0

                client = OpenAlexClient()
                calculator = LabelCalculator()

                # 分批处理，避免长事务
                for i in range(0, len(articles), batch_size):
                    chunk = articles[i : i + batch_size]
                    logger.info(f"处理批次: offset={i}, count={len(chunk)}")

                    for article in chunk:
                        try:
                            work = await client.get_work_by_doi(article.doi)

                            if work:
                                article.openalex_id = work["openalex_id"]
                                article.cited_by_count = work["cited_by_count"]
                                article.cited_by_percentile_year = work["cited_by_percentile_year"]
                                article.last_citation_update_at = datetime.now(timezone.utc)

                                labels = calculator.calculate_labels(
                                    publication_date=article.published_at_precise,
                                    category=article.category,
                                    cited_by_count=article.cited_by_count,
                                    cited_by_percentile_year=article.cited_by_percentile_year,
                                )
                                article.labels = labels
                                total_updated += 1
                            else:
                                labels = calculator.calculate_time_labels(
                                    article.published_at_precise
                                )
                                article.labels = labels
                                article.last_citation_update_at = datetime.now(timezone.utc)
                                total_failed += 1
                        except Exception as e:
                            logger.error(f"更新失败: {article.doi}, {e}")
                            try:
                                article.labels = calculator.calculate_time_labels(
                                    article.published_at_precise
                                )
                            except Exception:
                                pass
                            total_failed += 1

                        await asyncio.sleep(0.125)  # 限流

                    await session.commit()
                    logger.info(f"✅ 批次完成: 更新{total_updated}篇, 失败{total_failed}篇")

                await client.close()

                task_log.status = "success"
                task_log.total_fetched = len(articles)
                task_log.updated_count = total_updated
                task_log.finished_at = datetime.now(timezone.utc)
                await session.commit()

                return {
                    "timestamp": datetime.now().isoformat(),
                    "total_updated": total_updated,
                    "total_failed": total_failed,
                    "staleness_days": staleness_days,
                    "max_rows": max_rows,
                }
            except Exception as exc:
                task_log.status = "failed"
                task_log.error_message = str(exc)
                task_log.finished_at = datetime.now(timezone.utc)
                await session.commit()
                raise
    finally:
        await engine.dispose()


@shared_task(name="journals_tracking.refresh_time_labels")
def refresh_time_labels() -> Dict[str, Any]:
    """
    仅刷新时效性标签（new/recent），不触发 OpenAlex 网络请求。
    设计目的：保证 new/recent 每日准确（避免被 CITATION_STALENESS_DAYS=7 拖延）。
    """
    logger.info("开始刷新时效性标签...")
    return asyncio.run(_async_refresh_time_labels())


async def _async_refresh_time_labels() -> Dict[str, Any]:
    engine, SessionLocal = _build_session_factory()
    try:
        async with SessionLocal() as session:
            calculator = LabelCalculator()
            now = datetime.now(timezone.utc)
            cutoff_date = (now - timedelta(days=45)).date()

            task_log = CrawlTaskLog(
                task_type="time_labels_refresh",
                issn_l=None,
                status="running",
                started_at=now,
            )
            session.add(task_log)
            await session.commit()

            result = await session.execute(
                select(JournalArticle).where(
                    or_(
                        JournalArticle.publication_date >= cutoff_date,
                        JournalArticle.labels.contains(["new"]),
                        JournalArticle.labels.contains(["recent"]),
                    )
                )
            )
            articles = result.scalars().all()

            updated = 0
            for article in articles:
                existing = list(article.labels or [])
                keep = [l for l in existing if l not in ("new", "recent")]
                time_labels = calculator.calculate_time_labels(article.published_at_precise)
                article.labels = list(dict.fromkeys([*time_labels, *keep]))
                updated += 1

            task_log.status = "success"
            task_log.total_fetched = len(articles)
            task_log.updated_count = updated
            task_log.finished_at = datetime.now(timezone.utc)
            await session.commit()
            return {
                "timestamp": now.isoformat(),
                "updated": updated,
                "cutoff_date": cutoff_date.isoformat(),
            }
    finally:
        await engine.dispose()


@shared_task(name="journals_tracking.crawl_single_journal")
def crawl_single_journal(
    issn_l: str,
    cold_start: bool = False,
    from_date: str = "2020-01-01",
    abstract_strategy: str = "full",
    enable_llm_filter: bool = True,
    crossref_rows: int | None = None,
    crossref_sleep_seconds: float | None = None,
    window_days: int = 3,
    overlap_hours: int = 48,
    safety_gap_hours: int = 0,
) -> Dict[str, Any]:
    """
    爬取单个期刊（手动触发）
    
    Args:
        issn_l: 期刊ISSN-L
        cold_start: 是否冷启动
        window_days: 增量窗口天数（默认3；回补可传30）
        overlap_hours: 重叠窗口（小时）
        safety_gap_hours: 安全间隔（小时）
    """
    logger.info(
        f"爬取期刊: {issn_l}, cold_start={cold_start}, window_days={window_days}"
    )
    return asyncio.run(
        _async_crawl_single(
            issn_l=issn_l,
            cold_start=cold_start,
            from_date=from_date,
            abstract_strategy=abstract_strategy,
            enable_llm_filter=enable_llm_filter,
            crossref_rows=crossref_rows,
            crossref_sleep_seconds=crossref_sleep_seconds,
            window_days=window_days,
            overlap_hours=overlap_hours,
            safety_gap_hours=safety_gap_hours,
        )
    )


async def _async_crawl_single(
    issn_l: str,
    cold_start: bool,
    from_date: str,
    abstract_strategy: str,
    enable_llm_filter: bool,
    crossref_rows: int | None,
    crossref_sleep_seconds: float | None,
    window_days: int,
    overlap_hours: int,
    safety_gap_hours: int,
) -> Dict[str, Any]:
    """异步执行单个期刊爬取"""
    engine, SessionLocal = _build_session_factory()
    try:
        async with SessionLocal() as session:
            try:
                await init_cache()
            except Exception:
                pass
            crawler = JournalCrawler(session)
            
            try:
                if cold_start:
                    stats = await crawler.cold_start_crawl(
                        issn_l,
                        from_date=from_date,
                        abstract_strategy=abstract_strategy,
                        enable_llm_filter=enable_llm_filter,
                        crossref_rows=crossref_rows,
                        crossref_sleep_seconds=crossref_sleep_seconds,
                    )
                else:
                    stats = await crawler.incremental_crawl(
                        issn_l,
                        overlap_hours=overlap_hours,
                        window_days=window_days,
                        safety_gap_hours=safety_gap_hours,
                        enable_llm_filter=enable_llm_filter,
                        crossref_rows=crossref_rows,
                        crossref_sleep_seconds=crossref_sleep_seconds,
                    )
                
                await crawler.close()
                
                return {
                    "status": "success",
                    "issn_l": issn_l,
                    "stats": stats,
                }
            
            except Exception as e:
                await crawler.close()
                return {
                    "status": "failed",
                    "issn_l": issn_l,
                    "error": str(e),
                }
    finally:
        await engine.dispose()
