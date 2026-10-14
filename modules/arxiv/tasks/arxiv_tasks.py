"""
arXiv爬取定时任务
"""
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict
from core.task_runtime import run_async
from core.task_lock import task_lock
from zoneinfo import ZoneInfo
from core.celery_app import celery_app
from core.database import get_db_session, init_database
from core.config import settings
from sqlalchemy import text

from modules.arxiv.services.arxiv_crawler import ArxivCrawler
from modules.arxiv.services.biorxiv_crawler import BiorxivCrawler, BiorxivAPIError
from modules.arxiv.services.biorxiv_fallback import BiorxivEuropePMCCrawler
from modules.arxiv.services.llm_classifier import ArxivLLMClassifier
from modules.arxiv.services.arxiv_database import ArxivDatabaseService
from core.services.batch_translator import BatchTranslator

logger = logging.getLogger(__name__)


@celery_app.task(
    name="arxiv.incremental_crawl",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def arxiv_incremental_crawl(self):
    """
    arXiv增量爬取任务（每日凌晨3点UTC+8执行）

    爬取前1天的新提交文章
    """
    import asyncio

    async def _run():
        # Celery prefork 下每个子进程需要各自初始化数据库连接池（避免偶发 “Database not initialized”）
        await init_database()

        started_at = datetime.utcnow()
        task_type = "incremental"
        source = "arxiv"
        status = "running"
        error_message = None

        # 计算爬取日期范围：最近72小时（与模块1增量形式保持一致的“宽窗口+去重”策略）
        today = date.today()
        date_from = today - timedelta(days=3)
        date_to = today

        logger.info(f"开始增量爬取（最近72小时窗口）：{date_from} 至 {date_to}")

        try:
            # 初始化服务
            crawler = ArxivCrawler()
            llm_classifier = ArxivLLMClassifier(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
            )

            # L1层：arXiv API查询
            articles = crawler.crawl_date_range(date_from, date_to, batch_delay=5)
            total_fetched = len(articles)
            logger.info(f"L1召回：{total_fetched}篇文章")

            # L2层：LLM过滤与分类（增量任务保留翻译，便于前端使用）
            processed_articles = []
            batch_size = 20
            for i in range(0, len(articles), batch_size):
                batch = articles[i : i + batch_size]
                # 只做相关度判断 + 翻译，不再做4类分类（与冷启动回填保持同一阈值0.3）
                batch_processed = llm_classifier.process_batch(
                    batch,
                    threshold=0.3,
                    translate=False,
                    classify=False,
                )
                processed_articles.extend(batch_processed)
                logger.info(f"L2处理进度：{len(processed_articles)}/{total_fetched}")

            llm_processed = len(processed_articles)
            logger.info(f"L2处理完成：{llm_processed}篇通过相关度判断")

            # 入库
            async with get_db_session() as db:
                db_service = ArxivDatabaseService(db)
                new_inserted, updated_count = await db_service.upsert_articles(processed_articles)

                # 增量任务：为本次新增/更新的预印本文献补齐 title_zh（只补空缺）
                try:
                    arxiv_ids = [a.get("arxiv_id") for a in processed_articles if a.get("arxiv_id")]
                    if arxiv_ids:
                        result = await db.execute(
                            text(
                                """
                                select id
                                from arxiv_articles
                                where arxiv_id = any(:arxiv_ids)
                                  and (title_zh is null or length(title_zh)=0)
                                """
                            ),
                            {"arxiv_ids": arxiv_ids},
                        )
                        ids = [int(row[0]) for row in result.all()]
                        if ids:
                            translator = BatchTranslator()
                            for i in range(0, len(ids), 50):
                                await translator.translate_titles_for_arxiv(ids[i : i + 50], db)
                            logger.info("🈶 自动翻译预印本标题: %d 篇", len(ids))
                except Exception as e:
                    logger.warning("⚠️ 自动翻译预印本标题失败（忽略，不中断主流程）: %s", e)

                # 记录日志
                finished_at = datetime.utcnow()
                status = "success"
                await db_service.log_crawl_task(
                    task_type=task_type,
                    source=source,
                    status=status,
                    date_from=date_from,
                    date_to=date_to,
                    total_fetched=total_fetched,
                    llm_processed=llm_processed,
                    new_inserted=new_inserted,
                    updated_count=updated_count,
                    started_at=started_at,
                    finished_at=finished_at,
                )

                logger.info(
                    f"增量爬取完成：召回{total_fetched}篇，LLM处理{llm_processed}篇，"
                    f"新增{new_inserted}篇，更新{updated_count}篇"
                )

        except Exception as e:
            logger.error(f"增量爬取失败: {e}", exc_info=True)
            status = "failed"
            error_message = str(e)

            # 记录失败日志
            async with get_db_session() as db:
                db_service = ArxivDatabaseService(db)
                await db_service.log_crawl_task(
                    task_type=task_type,
                    source=source,
                    status=status,
                    date_from=date_from,
                    date_to=date_to,
                    error_message=error_message,
                    started_at=started_at,
                    finished_at=datetime.utcnow(),
                )

            # Celery重试
            raise self.retry(exc=e)

    # 运行异步任务（Python 3.11+ 下 Celery worker 线程默认无 event loop）
    run_async(_run())


def preprint_window(today: date, last_end: date | None):
    """Three-day overlap, resume outages, at most seven inclusive days per task."""
    start = today - timedelta(days=3)
    if last_end is not None:
        start = min(start, last_end - timedelta(days=1))
    start = max(date(2024, 1, 1), start)
    return start, min(today, start + timedelta(days=6))


@celery_app.task(name="biorxiv.incremental_crawl", bind=True, max_retries=3,
                 default_retry_delay=900, soft_time_limit=1740, time_limit=1800)
def biorxiv_incremental_crawl(self):
    try:
        with task_lock("biorxiv_incremental", ttl=1900) as acquired:
            if not acquired:
                return {"status": "already_running"}
            return run_async(_biorxiv_incremental())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=min(3600, 900 * (2 ** self.request.retries)))


async def _biorxiv_incremental():
    await init_database()
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    async with get_db_session() as db:
        primary_end = (await db.execute(text("""SELECT max(date_to) FROM arxiv_crawl_log
            WHERE source='biorxiv' AND task_type='incremental' AND status='success'"""))).scalar()
        fallback_end = (await db.execute(text("""SELECT max(date_to) FROM arxiv_crawl_log
            WHERE source='biorxiv' AND task_type IN ('incremental','incremental_fallback') AND status='success'"""))).scalar()

    async def fetch(crawler, task_type, last_end):
        start, end = preprint_window(today, last_end)
        async with get_db_session() as db:
            log_id = await ArxivDatabaseService(db).log_crawl_task(task_type=task_type, source="biorxiv",
                status="running", date_from=start, date_to=end, started_at=datetime.utcnow())
        try:
            articles = crawler.crawl_date_range(start, end, batch_delay=3)
            return articles, log_id, start, end
        except Exception as exc:
            await finish(log_id, "failed", error=str(exc))
            raise

    async def finish(log_id, status, fetched=0, processed=0, inserted=0, updated=0, error=None):
        # A fresh session records failure even after the article transaction rolled back.
        async with get_db_session() as db:
            await db.execute(text("""UPDATE arxiv_crawl_log SET status=:status,total_fetched=:fetched,
                llm_processed=:processed,new_inserted=:inserted,updated_count=:updated,error_message=:error,
                finished_at=:finished WHERE id=:id"""), dict(id=log_id,status=status,fetched=fetched,
                processed=processed,inserted=inserted,updated=updated,error=error,finished=datetime.utcnow()))
            await db.commit()

    provider, primary_error = "biorxiv", None
    try:
        articles, log_id, start, end = await fetch(BiorxivCrawler(), "incremental", primary_end)
    except BiorxivAPIError as exc:
        primary_error = str(exc)
        provider = "europe_pmc"
        articles, log_id, start, end = await fetch(BiorxivEuropePMCCrawler(), "incremental_fallback", fallback_end)

    try:
        fetched = len(articles)
        # The fallback only inserts missing DOIs. Official metadata can later reconcile them.
        async with get_db_session() as db:
            ids = [a["arxiv_id"] for a in articles]
            existing = dict((await db.execute(text("SELECT arxiv_id,version FROM arxiv_articles WHERE arxiv_id=any(:ids)"), {"ids": ids})).all()) if ids else {}
        articles = [a for a in articles if a["arxiv_id"] not in existing or
            (provider == "biorxiv" and (existing[a["arxiv_id"]] is None or a.get("version", 1) > existing[a["arxiv_id"]]))]
        processed = []
        classifier = ArxivLLMClassifier(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url, strict=True)
        try:
            for offset in range(0, len(articles), 20):
                processed.extend(classifier.process_batch(articles[offset:offset+20], threshold=0.3, translate=False, classify=False))
        finally:
            classifier.client.close()
        async with get_db_session() as db:
            inserted, updated = await ArxivDatabaseService(db).upsert_articles(processed)
            try:
                ids = [a["arxiv_id"] for a in processed]
                missing = (await db.execute(text("SELECT id FROM arxiv_articles WHERE arxiv_id=any(:ids) AND (title_zh IS NULL OR title_zh='')"), {"ids": ids})).scalars().all() if ids else []
                translator = BatchTranslator()
                for offset in range(0, len(missing), 50):
                    await translator.translate_titles_for_arxiv(missing[offset:offset+50], db)
            except Exception as exc:
                await db.rollback()
                logger.warning("BioRxiv title translation deferred: %s", type(exc).__name__)
        await finish(log_id, "success", fetched, len(processed), inserted, updated, primary_error)
    except Exception as exc:
        await finish(log_id, "failed", error=str(exc))
        raise

    # Continue bounded catch-up batches; fallback never advances the official checkpoint.
    if end < today:
        celery_app.send_task("biorxiv.incremental_crawl", queue="arxiv", countdown=60, expires=21600)
    return {"status": "success" if provider == "biorxiv" else "fallback_success", "provider": provider,
            "date_from": str(start), "date_to": str(end), "fetched": fetched,
            "classified": len(articles), "accepted": len(processed), "inserted": inserted, "updated": updated}


@celery_app.task(name="arxiv.backfill_by_month")
def arxiv_backfill_by_month(year: int, month: int):
    """
    arXiv历史回填任务（按月份）

    Args:
        year: 年份
        month: 月份
    """
    import asyncio
    from calendar import monthrange

    async def _run():
        await init_database()

        started_at = datetime.utcnow()
        task_type = "backfill"
        source = "arxiv"
        status = "running"

        # 计算该月的起止日期
        _, last_day = monthrange(year, month)
        date_from = date(year, month, 1)
        date_to = date(year, month, last_day)

        logger.info(f"开始回填：{year}-{month:02d} ({date_from} 至 {date_to})")

        try:
            # 初始化服务
            crawler = ArxivCrawler()
            llm_classifier = ArxivLLMClassifier(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
            )

            # L1层：arXiv API查询
            articles = crawler.crawl_date_range(date_from, date_to, batch_delay=5)
            total_fetched = len(articles)
            logger.info(f"L1召回：{total_fetched}篇文章")

            # L2层：LLM过滤与分类（回填任务关闭翻译以降低LLM成本）
            processed_articles = []
            batch_size = 20
            for i in range(0, len(articles), batch_size):
                batch = articles[i : i + batch_size]
                # 回填任务：只做相关度判断，不分类、不翻译（与冷启动脚本同一阈值0.3）
                batch_processed = llm_classifier.process_batch(
                    batch,
                    threshold=0.3,
                    translate=False,
                    classify=False,
                )
                processed_articles.extend(batch_processed)
                logger.info(f"L2处理进度：{len(processed_articles)}/{total_fetched}")

            llm_processed = len(processed_articles)
            logger.info(f"L2处理完成：{llm_processed}篇通过相关度判断")

            # 入库
            async with get_db_session() as db:
                db_service = ArxivDatabaseService(db)
                new_inserted, updated_count = await db_service.upsert_articles(processed_articles)

                # 记录日志
                finished_at = datetime.utcnow()
                status = "success"
                await db_service.log_crawl_task(
                    task_type=task_type,
                    source=source,
                    status=status,
                    date_from=date_from,
                    date_to=date_to,
                    total_fetched=total_fetched,
                    llm_processed=llm_processed,
                    new_inserted=new_inserted,
                    updated_count=updated_count,
                    started_at=started_at,
                    finished_at=finished_at,
                )

                logger.info(
                    f"{year}-{month:02d}回填完成：召回{total_fetched}篇，LLM处理{llm_processed}篇，"
                    f"新增{new_inserted}篇，更新{updated_count}篇"
                )

        except Exception as e:
            logger.error(f"{year}-{month:02d}回填失败: {e}", exc_info=True)
            status = "failed"
            error_message = str(e)

            async with get_db_session() as db:
                db_service = ArxivDatabaseService(db)
                await db_service.log_crawl_task(
                    task_type=task_type,
                    source=source,
                    status=status,
                    date_from=date_from,
                    date_to=date_to,
                    error_message=error_message,
                    started_at=started_at,
                    finished_at=datetime.utcnow(),
                )

            raise

    run_async(_run())


@celery_app.task(name="biorxiv.backfill_by_month")
def biorxiv_backfill_by_month(year: int, month: int):
    """BioRxiv 历史回填任务（按月份）"""
    import asyncio
    from calendar import monthrange

    async def _run():
        await init_database()

        started_at = datetime.utcnow()
        task_type = "backfill"
        source = "biorxiv"
        status = "running"

        _, last_day = monthrange(year, month)
        date_from = date(year, month, 1)
        date_to = date(year, month, last_day)

        logger.info(f"开始 BioRxiv 回填：{year}-{month:02d} ({date_from} 至 {date_to})")

        try:
            crawler = BiorxivCrawler()
            llm_classifier = ArxivLLMClassifier(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
            )

            articles = crawler.crawl_date_range(date_from, date_to, batch_delay=5)
            total_fetched = len(articles)
            logger.info(f"BioRxiv L1召回：{total_fetched}篇文章")

            processed_articles: List[Dict] = []
            batch_size = 20
            for i in range(0, len(articles), batch_size):
                batch = articles[i : i + batch_size]
                batch_processed = llm_classifier.process_batch(
                    batch,
                    threshold=0.3,
                    translate=False,
                    classify=False,
                )
                processed_articles.extend(batch_processed)
                logger.info(f"BioRxiv L2处理进度：{len(processed_articles)}/{total_fetched}")

            llm_processed = len(processed_articles)
            logger.info(f"BioRxiv L2处理完成：{llm_processed}篇通过相关度判断")

            async with get_db_session() as db:
                db_service = ArxivDatabaseService(db)
                new_inserted, updated_count = await db_service.upsert_articles(processed_articles)

                finished_at = datetime.utcnow()
                status = "success"
                await db_service.log_crawl_task(
                    task_type=task_type,
                    source=source,
                    status=status,
                    date_from=date_from,
                    date_to=date_to,
                    total_fetched=total_fetched,
                    llm_processed=llm_processed,
                    new_inserted=new_inserted,
                    updated_count=updated_count,
                    started_at=started_at,
                    finished_at=finished_at,
                )

                logger.info(
                    f"BioRxiv {year}-{month:02d}回填完成：召回{total_fetched}篇，LLM处理{llm_processed}篇，"
                    f"新增{new_inserted}篇，更新{updated_count}篇"
                )

        except Exception as e:
            logger.error(f"BioRxiv {year}-{month:02d}回填失败: {e}", exc_info=True)
            status = "failed"
            error_message = str(e)

            async with get_db_session() as db:
                db_service = ArxivDatabaseService(db)
                await db_service.log_crawl_task(
                    task_type=task_type,
                    source=source,
                    status=status,
                    date_from=date_from,
                    date_to=date_to,
                    error_message=error_message,
                    started_at=started_at,
                    finished_at=datetime.utcnow(),
                )

            raise

    run_async(_run())
