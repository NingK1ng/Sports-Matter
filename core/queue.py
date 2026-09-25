"""
Celery任务队列配置

提供异步任务调度和定时任务功能
"""

import asyncio
from datetime import datetime, timedelta
import pytz
from celery import Celery
from celery.schedules import crontab
from sqlalchemy import text

from core.config import settings
from core.cache import init_cache, get_redis
from core.database import get_session_factory, init_database

# 创建Celery应用
celery_app = Celery(
    "sports_matter",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        'modules.literature_stream.tasks.incremental_tasks',  # 文献流新增量
        'modules.literature_stream.tasks.crawler_tasks',  # 文献流爬取
        'modules.journals.tasks.crawler_tasks',  # 顶刊追踪
        'modules.journals.tasks.enrich_tasks',  # 顶刊数据补齐
        'modules.literature_pool.tasks.search_tasks',  # 文献池搜索
        'modules.literature_pool.tasks.wiw_tasks',  # WiW生成
        'modules.literature_pool.tasks.cleanup_tasks',  # 清理任务
        'modules.knowledge_graph.tasks.snapshot_tasks',  # 知识图谱快照
        'modules.literature_stream.tasks.enrich_tasks',  # IF导入与回填
        'modules.arxiv.tasks.arxiv_tasks',  # arXiv前沿爬取
    ]
)

# Celery配置
celery_app.conf.update(
    # 时区配置（UTC+8 = Asia/Shanghai）
    timezone='Asia/Shanghai',
    enable_utc=False,

    # 任务配置
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    task_track_started=True,
    # 取消全局超时：模块2顶刊/回补任务可能超过1小时，避免被硬杀导致状态无法推进
    task_time_limit=None,
    task_soft_time_limit=None,

    # 结果后端配置
    result_expires=86400,  # 结果保留24小时
    result_backend_transport_options={'master_name': 'mymaster'},

    # Worker配置
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)

# Beat定时任务配置
celery_app.conf.beat_schedule = {
    # 模块1：文献流 - 每日凌晨2点（UTC+8）
    'daily-incremental-crawl': {
        'task': 'literature_stream.daily_incremental_crawl',
        'schedule': crontab(hour=2, minute=0),  # UTC+8 02:00
        'options': {'queue': 'literature_stream'},
    },
    # 文献流：IF映射导入（在增量抓取前执行）
    'literature-if-import': {
        'task': 'literature_stream.import_if_from_excel',
        'schedule': crontab(hour=1, minute=40),  # UTC+8 01:40
        'options': {'queue': 'literature_stream'},
    },
    # 文献流：IF回填近期文献
    'literature-if-enrich-recent': {
        'task': 'literature_stream.enrich_if_recent',
        'schedule': crontab(hour=2, minute=40),  # UTC+8 02:40
        'options': {'queue': 'literature_stream'},
    },

    # 模块2：顶刊追踪 - 增量爬取（每日凌晨4点）
    'journals-incremental-crawl': {
        'task': 'journals_tracking.crawl_all_journals',
        'schedule': crontab(hour=4, minute=0),  # UTC+8 04:00
        'options': {'queue': 'journals_tracking'},
    },
    # 顶刊追踪 - 7天回补（每周日凌晨3点）
    'journals-rollup-7days': {
        'task': 'journals_tracking.rollup_7days',
        'schedule': crontab(hour=3, minute=0, day_of_week=0),  # 每周日 03:00
        'options': {'queue': 'journals_tracking'},
    },
    # 顶刊追踪 - PubMed 摘要补齐
    'journals-enrich-abstracts': {
        'task': 'journals_tracking.enrich_missing_abstracts',
        'schedule': crontab(hour=4, minute=30),  # UTC+8 04:30
        'options': {'queue': 'journals_tracking'},
    },
    # 顶刊追踪 - 更新被引数（每日凌晨5点）
    'journals-update-citations': {
        'task': 'journals_tracking.update_citation_counts',
        'schedule': crontab(hour=5, minute=0),  # UTC+8 05:00
        'options': {'queue': 'journals_tracking'},
    },
    # 顶刊追踪 - 刷新时效性标签（每日凌晨5:10）
    'journals-refresh-time-labels': {
        'task': 'journals_tracking.refresh_time_labels',
        'schedule': crontab(hour=5, minute=10),  # UTC+8 05:10
        'options': {'queue': 'journals_tracking'},
    },
    # CNS：运动相关预计算（规则召回 + LLM判定）
    'journals-cns-sports-classify': {
        'task': 'journals_tracking.classify_cns_sports_related',
        # 放在顶刊任务完成后，避免与 04:00~05:10 高峰抢资源
        'schedule': crontab(hour=5, minute=20),  # UTC+8 05:20
        'options': {'queue': 'journals_tracking'},
    },

    # 模块4：文献池 - 模块1轨道文献搜索（每日23:30）
    'pool-search-stream-articles': {
        'task': 'literature_pool.search_all_subscriptions_stream',
        'schedule': crontab(hour=23, minute=30),  # UTC+8 23:30
        'options': {'queue': 'literature_pool'},
    },
    # 文献池 - WiW生成调度（每日凌晨0:10）
    'pool-generate-wiw': {
        'task': 'literature_pool.generate_all_subscriptions_wiw',
        'schedule': crontab(hour=0, minute=10),  # UTC+8 00:10
        'options': {'queue': 'literature_pool'},
    },
    # 文献池 - 清理过期映射（每日凌晨1点）
    'pool-cleanup-expired-mappings': {
        'task': 'literature_pool.cleanup_expired_mappings',
        'schedule': crontab(hour=1, minute=0),  # UTC+8 01:00
        'options': {'queue': 'literature_pool'},
    },
    # 文献池 - 清理孤儿WiW（每周一凌晨2点）
    'pool-cleanup-orphan-wiw': {
        'task': 'literature_pool.cleanup_orphan_wiw',
        'schedule': crontab(hour=2, minute=0, day_of_week=1),  # 每周一 02:00
        'options': {'queue': 'literature_pool'},
    },

    # 模块5：知识图谱 - 1天快照
    'graph-build-snapshot-1d': {
        'task': 'knowledge_graph.build_snapshot_1d',
        # 1d 快照需等待模块1/2的日更入库完成（避免仅聚类到少量旧文献）
        'schedule': crontab(hour=5, minute=30),  # 每天 05:30
        'options': {'queue': 'knowledge_graph'},
    },
    # 知识图谱 - 7天快照
    'graph-build-snapshot-7d': {
        'task': 'knowledge_graph.build_snapshot_7d',
        'schedule': crontab(hour=5, minute=45),  # 每天 05:45
        'options': {'queue': 'knowledge_graph'},
    },
    # 知识图谱 - 30天快照
    'graph-build-snapshot-30d': {
        'task': 'knowledge_graph.build_snapshot_30d',
        # 30d窗口随每日上新变化明显，改为每日更新（避开 04:00~05:10 顶刊任务高峰）
        'schedule': crontab(hour=6, minute=0),  # 每天 06:00
        'options': {'queue': 'knowledge_graph'},
    },

    # 知识图谱 - 预生成Top社区WiW摘要（每日，避免首位用户等待）
    'graph-precompute-wiw': {
        'task': 'knowledge_graph.precompute_wiw',
        # 等待 1d/7d/30d 快照全部生成完成后再跑
        'schedule': crontab(hour=6, minute=10),  # 每天 06:10
        'options': {'queue': 'knowledge_graph'},
    },
    # 知识图谱 - 180天快照
    'graph-build-snapshot-180d': {
        'task': 'knowledge_graph.build_snapshot_180d',
        # 180d窗口计算量较大，改为每2个月更新一次（偶数月1日 06:30）
        'schedule': crontab(hour=6, minute=30, day_of_month=1, month_of_year='2,4,6,8,10,12'),
        'options': {'queue': 'knowledge_graph'},
    },

    # 模块8：arXiv前沿 - 增量爬取（每日凌晨3点）
    'arxiv-incremental-crawl': {
        'task': 'arxiv.incremental_crawl',
        'schedule': crontab(hour=3, minute=0),  # UTC+8 03:00
        'options': {'queue': 'arxiv'},
    },

    # 模块8：BioRxiv前沿 - 增量爬取（每日凌晨3:30）
    'biorxiv-incremental-crawl': {
        'task': 'biorxiv.incremental_crawl',
        'schedule': crontab(hour=3, minute=30),  # UTC+8 03:30
        'options': {'queue': 'arxiv'},
    },
    # 维护：清理卡住的running任务（每小时第15分钟）
    'maintenance-cleanup-stale-crawl-log': {
        'task': 'maintenance.cleanup_stale_crawl_log',
        'schedule': crontab(minute=15),
        'options': {'queue': 'literature_stream'},
    },
    # 维护：清理顶刊任务日志中的卡住记录（每小时第16分钟）
    'maintenance-cleanup-stale-crawl-log-journals': {
        'task': 'maintenance.cleanup_stale_crawl_log_journals',
        'schedule': crontab(minute=16),
        'options': {'queue': 'journals_tracking'},
    },
    # 维护：补跑当日错过的“日更任务”（每小时第05分钟）
    'maintenance-ensure-daily-jobs': {
        'task': 'maintenance.ensure_daily_jobs',
        'schedule': crontab(minute=5),
        'options': {'queue': 'celery'},
    },
}

# 路由配置
celery_app.conf.task_routes = {
    'literature_stream.*': {'queue': 'literature_stream'},
    'journals_tracking.*': {'queue': 'journals_tracking'},
    'literature_pool.*': {'queue': 'literature_pool'},
    'knowledge_graph.*': {'queue': 'knowledge_graph'},
    'arxiv.*': {'queue': 'arxiv'},
    'biorxiv.*': {'queue': 'arxiv'},  # BioRxiv与arXiv使用同一队列
}


# 任务装饰器示例
@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    retry_backoff_max=240,
    retry_jitter=True,
)
def example_task(self, arg1, arg2):
    """
    示例任务

    Args:
        arg1: 参数1
        arg2: 参数2

    Returns:
        dict: 任务结果

    Raises:
        Exception: 任务执行失败
    """
    try:
        # 执行任务逻辑
        result = {"status": "success", "data": f"{arg1} + {arg2}"}
        return result
    except Exception as exc:
        # 任务失败，触发重试
        raise self.retry(exc=exc)


@celery_app.task(name="maintenance.cleanup_stale_crawl_log")
def cleanup_stale_crawl_log() -> int:
    """
    清理超过2小时未完成的running爬取任务，防止后续定时被卡住
    """
    try:
        session_factory = get_session_factory()
    except Exception:
        try:
            asyncio.run(init_database())
            session_factory = get_session_factory()
        except Exception as e:
            print(f"⚠️ 无法获取数据库会话: {e}")
            return 0

    async def _run():
        async with session_factory() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE crawl_task_log
                    SET status = 'failed',
                        error_message = 'auto-reset stale running',
                        finished_at = NOW()
                    WHERE status = 'running'
                      AND started_at < NOW() - INTERVAL '7 days'
                    """
                )
            )
            await session.commit()
            return result.rowcount or 0

    try:
        updated = asyncio.run(_run())
        if updated:
            print(f"🧹 清理卡住的任务 {updated} 条")
        return updated
    except Exception as e:
        print(f"❌ 清理卡住任务失败: {e}")
        return 0


@celery_app.task(name="maintenance.cleanup_stale_crawl_log_journals")
def cleanup_stale_crawl_log_journals() -> int:
    """
    清理顶刊追踪的卡住任务（crawl_task_log_journals）
    """
    try:
        session_factory = get_session_factory()
    except Exception:
        try:
            asyncio.run(init_database())
            session_factory = get_session_factory()
        except Exception as e:
            print(f"⚠️ 无法获取数据库会话: {e}")
            return 0

    async def _run():
        async with session_factory() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE crawl_task_log_journals
                    SET status = 'failed',
                        error_message = 'auto-reset stale running',
                        finished_at = NOW()
                    WHERE status = 'running'
                      AND started_at < NOW() - INTERVAL '7 days'
                    """
                )
            )
            await session.commit()
            return result.rowcount or 0

    try:
        updated = asyncio.run(_run())
        if updated:
            print(f"🧹 清理顶刊卡住的任务 {updated} 条")
        return updated
    except Exception as e:
        print(f"❌ 清理顶刊卡住任务失败: {e}")
        return 0


@celery_app.task(name="maintenance.ensure_daily_jobs")
def ensure_daily_jobs() -> dict:
    """
    兜底补跑机制：当 Celery Beat/Worker 重启导致错过定时点时，自动补派发当日应执行的任务。

    覆盖范围（UTC+8）：
    - 模块1 daily_incremental_crawl：02:00
    - 模块2 journals crawl：04:00（按期刊检查缺失后派发 crawl_single_journal）
    - 模块2 citations 更新：05:00
    - 模块2 time labels 刷新：05:10
    - 模块2 CNS：运动相关预计算：05:20
    """
    try:
        session_factory = get_session_factory()
    except Exception:
        try:
            asyncio.run(init_database())
            session_factory = get_session_factory()
        except Exception as e:
            return {"status": "failed", "error": f"cannot_init_db: {e}"}

    tz = pytz.timezone("Asia/Shanghai")
    now_local = datetime.now(tz)

    def _target_day_window(hour: int, minute: int) -> tuple[datetime, datetime]:
        today = now_local.date()
        scheduled_today = tz.localize(datetime(today.year, today.month, today.day, hour, minute))
        target_day = today if now_local >= scheduled_today else today - timedelta(days=1)
        day_start = tz.localize(datetime(target_day.year, target_day.month, target_day.day, 0, 0, 0))
        return day_start, day_start + timedelta(days=1)

    async def _run() -> dict:
        actions: dict = {"timestamp_local": now_local.isoformat()}
        redis = None
        try:
            await init_cache()
            redis = get_redis()
        except Exception:
            # Redis 仅用于兜底去重；不可用时不阻塞补跑
            redis = None

        async def _claim_once(key: str, ttl_seconds: int = 36 * 3600) -> bool:
            if redis is None:
                return True
            try:
                # SET key value NX EX ttl
                ok = await redis.set(key, b"1", ex=ttl_seconds, nx=True)
                return bool(ok)
            except Exception:
                # 缓存异常不影响补跑
                return True

        def _marker_key(job: str, day: datetime, suffix: str | None = None) -> str:
            base = f"sm:ensure:{job}:{day.date().isoformat()}"
            return f"{base}:{suffix}" if suffix else base

        async with session_factory() as session:
            # 模块1：每日增量（依赖 crawl_task_log）
            lit_start_local, lit_end_local = _target_day_window(2, 0)
            lit_start_utc = lit_start_local.astimezone(pytz.UTC).replace(tzinfo=None)
            lit_end_utc = lit_end_local.astimezone(pytz.UTC).replace(tzinfo=None)

            lit_success = await session.execute(
                text(
                    """
                    SELECT 1
                    FROM crawl_task_log
                    WHERE task_type = 'incremental_daily'
                      AND status = 'success'
                      AND started_at >= :start_utc
                      AND started_at < :end_utc
                    LIMIT 1
                    """
                ),
                {"start_utc": lit_start_utc, "end_utc": lit_end_utc},
            )
            lit_running = await session.execute(
                text(
                    """
                    SELECT 1
                    FROM crawl_task_log
                    WHERE task_type = 'incremental_daily'
                      AND status = 'running'
                      AND started_at >= :start_utc
                      AND started_at < :end_utc
                    LIMIT 1
                    """
                ),
                {"start_utc": lit_start_utc, "end_utc": lit_end_utc},
            )
            if lit_success.first() is not None:
                actions["literature_stream_daily"] = "ok"
            elif lit_running.first() is not None:
                actions["literature_stream_daily"] = "running"
            else:
                if await _claim_once(_marker_key("literature_stream_daily", lit_start_local)):
                    celery_app.send_task(
                        "literature_stream.daily_incremental_crawl",
                        queue="literature_stream",
                    )
                    actions["literature_stream_daily"] = "dispatched"
                else:
                    actions["literature_stream_daily"] = "already_dispatched"

            # 模块2：顶刊增量（按期刊检查 crawl_task_log_journals）
            j_start_local, j_end_local = _target_day_window(4, 0)
            j_start_utc = j_start_local.astimezone(pytz.UTC)
            j_end_utc = j_end_local.astimezone(pytz.UTC)

            all_journals_res = await session.execute(
                text("SELECT issn_l FROM journal_metadata_tracked")
            )
            all_journals = [row[0] for row in all_journals_res.fetchall()]

            if all_journals:
                done_res = await session.execute(
                    text(
                        """
                        SELECT issn_l, bool_or(status = 'success') AS has_success, bool_or(status = 'running') AS has_running
                        FROM crawl_task_log_journals
                        WHERE task_type = 'incremental'
                          AND status IN ('success', 'running')
                          AND started_at >= :start_utc
                          AND started_at < :end_utc
                        GROUP BY issn_l
                        """
                    ),
                    {"start_utc": j_start_utc, "end_utc": j_end_utc},
                )
                done_rows = done_res.fetchall()
                done_set = {row[0] for row in done_rows}
                missing = [issn for issn in all_journals if issn not in done_set]
                if not missing:
                    actions["journals_incremental"] = "ok"
                else:
                    dispatched: list[str] = []
                    already: list[str] = []
                    for idx, issn_l in enumerate(missing):
                        key = _marker_key("journals_incremental", j_start_local, suffix=issn_l)
                        if await _claim_once(key):
                            celery_app.send_task(
                                "journals_tracking.crawl_single_journal",
                                args=[issn_l],
                                queue="journals_tracking",
                                countdown=idx * 2,
                            )
                            dispatched.append(issn_l)
                        else:
                            already.append(issn_l)
                    actions["journals_incremental"] = {
                        "missing": missing,
                        "dispatched": dispatched,
                        "already_dispatched": already,
                    }
            else:
                actions["journals_incremental"] = "skipped(no_journals)"

            # 模块2：被引更新（依赖 crawl_task_log_journals 的 citation_update）
            c_start_local, c_end_local = _target_day_window(5, 0)
            c_start_utc = c_start_local.astimezone(pytz.UTC)
            c_end_utc = c_end_local.astimezone(pytz.UTC)

            cit_success = await session.execute(
                text(
                    """
                    SELECT 1
                    FROM crawl_task_log_journals
                    WHERE task_type = 'citation_update'
                      AND status = 'success'
                      AND started_at >= :start_utc
                      AND started_at < :end_utc
                    LIMIT 1
                    """
                ),
                {"start_utc": c_start_utc, "end_utc": c_end_utc},
            )
            cit_running = await session.execute(
                text(
                    """
                    SELECT 1
                    FROM crawl_task_log_journals
                    WHERE task_type = 'citation_update'
                      AND status = 'running'
                      AND started_at >= :start_utc
                      AND started_at < :end_utc
                    LIMIT 1
                    """
                ),
                {"start_utc": c_start_utc, "end_utc": c_end_utc},
            )
            if cit_success.first() is not None:
                actions["journals_citations"] = "ok"
            elif cit_running.first() is not None:
                actions["journals_citations"] = "running"
            else:
                if await _claim_once(_marker_key("journals_citations", c_start_local)):
                    celery_app.send_task(
                        "journals_tracking.update_citation_counts",
                        queue="journals_tracking",
                    )
                    actions["journals_citations"] = "dispatched"
                else:
                    actions["journals_citations"] = "already_dispatched"

            # 模块2：时效性标签刷新
            t_start_local, t_end_local = _target_day_window(5, 10)
            t_start_utc = t_start_local.astimezone(pytz.UTC)
            t_end_utc = t_end_local.astimezone(pytz.UTC)
            t_success = await session.execute(
                text(
                    """
                    SELECT 1
                    FROM crawl_task_log_journals
                    WHERE task_type = 'time_labels_refresh'
                      AND status = 'success'
                      AND started_at >= :start_utc
                      AND started_at < :end_utc
                    LIMIT 1
                    """
                ),
                {"start_utc": t_start_utc, "end_utc": t_end_utc},
            )
            t_running = await session.execute(
                text(
                    """
                    SELECT 1
                    FROM crawl_task_log_journals
                    WHERE task_type = 'time_labels_refresh'
                      AND status = 'running'
                      AND started_at >= :start_utc
                      AND started_at < :end_utc
                    LIMIT 1
                    """
                ),
                {"start_utc": t_start_utc, "end_utc": t_end_utc},
            )
            if t_success.first() is not None:
                actions["journals_time_labels"] = "ok"
            elif t_running.first() is not None:
                actions["journals_time_labels"] = "running"
            else:
                if await _claim_once(_marker_key("journals_time_labels", t_start_local)):
                    celery_app.send_task(
                        "journals_tracking.refresh_time_labels",
                        queue="journals_tracking",
                    )
                    actions["journals_time_labels"] = "dispatched"
                else:
                    actions["journals_time_labels"] = "already_dispatched"

            # 模块2：CNS 运动相关预计算（规则召回 + LLM 判定）
            s_start_local, s_end_local = _target_day_window(5, 20)
            s_start_utc = s_start_local.astimezone(pytz.UTC)
            s_end_utc = s_end_local.astimezone(pytz.UTC)
            s_success = await session.execute(
                text(
                    """
                    SELECT 1
                    FROM crawl_task_log_journals
                    WHERE task_type = 'cns_sports_classify'
                      AND status = 'success'
                      AND started_at >= :start_utc
                      AND started_at < :end_utc
                    LIMIT 1
                    """
                ),
                {"start_utc": s_start_utc, "end_utc": s_end_utc},
            )
            s_running = await session.execute(
                text(
                    """
                    SELECT 1
                    FROM crawl_task_log_journals
                    WHERE task_type = 'cns_sports_classify'
                      AND status = 'running'
                      AND started_at >= :start_utc
                      AND started_at < :end_utc
                    LIMIT 1
                    """
                ),
                {"start_utc": s_start_utc, "end_utc": s_end_utc},
            )
            if s_success.first() is not None:
                actions["cns_sports_classify"] = "ok"
            elif s_running.first() is not None:
                actions["cns_sports_classify"] = "running"
            else:
                # 分类任务失败时需要可重试，缩短去重TTL（避免一天内永久不再补跑）
                if await _claim_once(_marker_key("cns_sports_classify", s_start_local), ttl_seconds=2 * 3600):
                    celery_app.send_task(
                        "journals_tracking.classify_cns_sports_related",
                        queue="journals_tracking",
                    )
                    actions["cns_sports_classify"] = "dispatched"
                else:
                    actions["cns_sports_classify"] = "already_dispatched"

        return actions

    try:
        return asyncio.run(_run())
    except Exception as e:
        return {"status": "failed", "error": str(e)}
