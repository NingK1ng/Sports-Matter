"""
arXiv爬取定时任务
"""
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict
from core.celery_app import celery_app
from core.database import get_db_session, init_database
from core.config import settings
from sqlalchemy import text

from modules.arxiv.services.arxiv_crawler import ArxivCrawler
from modules.arxiv.services.biorxiv_crawler import BiorxivCrawler
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
    asyncio.run(_run())


@celery_app.task(
    name="biorxiv.incremental_crawl",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def biorxiv_incremental_crawl(self):
    """BioRxiv 增量爬取任务（最近72小时窗口）"""
    import asyncio

    async def _run():
        await init_database()

        started_at = datetime.utcnow()
        task_type = "incremental"
        source = "biorxiv"
        status = "running"
        error_message = None

        today = date.today()
        date_from = today - timedelta(days=3)
        date_to = today

        logger.info(f"开始 BioRxiv 增量爬取（最近72小时窗口）：{date_from} 至 {date_to}")

        try:
            crawler = BiorxivCrawler()
            llm_classifier = ArxivLLMClassifier(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
            )

            # L1：BioRxiv API 按日期范围抓取
            articles = crawler.crawl_date_range(date_from, date_to, batch_delay=5)
            total_fetched = len(articles)
            logger.info(f"BioRxiv L1召回：{total_fetched}篇文章")

            # L2：只做相关度判断（与冷启动逻辑一致），保留翻译
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
                    f"BioRxiv 增量爬取完成：召回{total_fetched}篇，LLM处理{llm_processed}篇，"
                    f"新增{new_inserted}篇，更新{updated_count}篇"
                )

        except Exception as e:
            logger.error(f"BioRxiv 增量爬取失败: {e}", exc_info=True)
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

            raise self.retry(exc=e)

    asyncio.run(_run())


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

    asyncio.run(_run())


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

    asyncio.run(_run())
