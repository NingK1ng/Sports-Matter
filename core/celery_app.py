"""
Celery应用配置
"""
from celery import Celery
from celery.schedules import crontab
from core.config import settings

# 创建Celery应用
celery_app = Celery(
    "sports_matter",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        'modules.literature_stream.tasks.crawler_tasks',
        'modules.journals.tasks.crawler_tasks',
        'modules.journals.tasks.enrich_tasks',
        'modules.literature_pool.tasks.search_tasks',
        'modules.literature_pool.tasks.wiw_tasks',
        'modules.literature_pool.tasks.cleanup_tasks',
        'modules.knowledge_graph.tasks.snapshot_tasks',  # 知识图谱快照任务
        'modules.literature_stream.tasks.enrich_tasks',  # 文献流 IF 导入与回填
        'modules.arxiv.tasks.arxiv_tasks',  # arXiv前沿爬取任务
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
    # 取消全局超时，改用任务级别配置（尤其是 journals 任务需要长时间处理）
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
    # 文献流：IF映射导入（在增量抓取前执行，确保映射最新）
    'literature-if-import': {
        'task': 'literature_stream.import_if_from_excel',
        'schedule': crontab(hour=1, minute=40),  # UTC+8 01:40（抓取前）
        'options': {'queue': 'literature_stream'},
    },
    # 文献流：IF回填近期文献（抓取后执行，兜底更新）
    'literature-if-enrich-recent': {
        'task': 'literature_stream.enrich_if_recent',
        'schedule': crontab(hour=2, minute=40),  # UTC+8 02:40（抓取后）
        'options': {'queue': 'literature_stream'},
    },
    
    # 模块2：顶刊追踪 - 增量爬取（每日凌晨4点，UTC+8，3天窗口）
    'journals-incremental-crawl': {
        'task': 'journals_tracking.crawl_all_journals',
        'schedule': crontab(hour=4, minute=0),  # UTC+8 04:00
        'options': {'queue': 'journals_tracking'},
    },
    
    # 模块2：顶刊追踪 - 7天回补（每周日凌晨3点，UTC+8）
    'journals-rollup-7days': {
        'task': 'journals_tracking.rollup_7days',
        'schedule': crontab(hour=3, minute=0, day_of_week=0),  # 每周日 03:00
        'options': {'queue': 'journals_tracking'},
    },
    
    # 模块2：顶刊追踪 - PubMed 摘要补齐（增量后、被引更新前）
    'journals-enrich-abstracts': {
        'task': 'journals_tracking.enrich_missing_abstracts',
        'schedule': crontab(hour=4, minute=30),  # UTC+8 04:30
        'options': {'queue': 'journals_tracking'},
    },

    # 模块2：顶刊追踪 - 更新被引数（每日凌晨5点，UTC+8）
    'journals-update-citations': {
        'task': 'journals_tracking.update_citation_counts',
        'schedule': crontab(hour=5, minute=0),  # UTC+8 05:00
        'options': {'queue': 'journals_tracking'},
    },
    # CNS：运动相关预计算（规则召回 + LLM判定）
    'journals-cns-sports-classify': {
        'task': 'journals_tracking.classify_cns_sports_related',
        'schedule': crontab(hour=5, minute=20),  # UTC+8 05:20
        'options': {'queue': 'journals_tracking'},
    },
    
    # 模块4：文献池 - 模块1轨道文献搜索（每日23:30，UTC+8，提前搜索）
    'pool-search-stream-articles': {
        'task': 'literature_pool.search_all_subscriptions_stream',
        'schedule': crontab(hour=23, minute=30),  # UTC+8 23:30（提前到WiW生成前）
        'options': {'queue': 'literature_pool'},
    },
    
    # 模块4：文献池 - WiW生成调度（每日凌晨0:10，UTC+8，确保搜索完成）
    'pool-generate-wiw': {
        'task': 'literature_pool.generate_all_subscriptions_wiw',
        'schedule': crontab(hour=0, minute=10),  # UTC+8 00:10（延后到搜索后）
        'options': {'queue': 'literature_pool'},
    },
    
    # 模块4：文献池 - 清理过期映射（每日凌晨1点，UTC+8）
    'pool-cleanup-expired-mappings': {
        'task': 'literature_pool.cleanup_expired_mappings',
        'schedule': crontab(hour=1, minute=0),  # UTC+8 01:00
        'options': {'queue': 'literature_pool'},
    },
    
    # 模块4：文献池 - 清理孤儿WiW（每周一凌晨2点，UTC+8）
    'pool-cleanup-orphan-wiw': {
        'task': 'literature_pool.cleanup_orphan_wiw',
        'schedule': crontab(hour=2, minute=0, day_of_week=1),  # 每周一 02:00
        'options': {'queue': 'literature_pool'},
    },
    
    # 模块5：知识图谱 - 1天快照（每天凌晨2点，UTC+8）
    'graph-build-snapshot-1d': {
        'task': 'knowledge_graph.build_snapshot_1d',
        # 1d 快照需等待模块1/2的日更入库完成（避免仅聚类到少量旧文献）
        'schedule': crontab(hour=5, minute=30),  # 每天 05:30
        'options': {'queue': 'knowledge_graph'},
    },
    
    # 模块5：知识图谱 - 7天快照（每天凌晨3点，UTC+8）
    'graph-build-snapshot-7d': {
        'task': 'knowledge_graph.build_snapshot_7d',
        'schedule': crontab(hour=5, minute=45),  # 每天 05:45
        'options': {'queue': 'knowledge_graph'},
    },
    
    # 模块5：知识图谱 - 30天快照（每周一凌晨2点，UTC+8）
    'graph-build-snapshot-30d': {
        'task': 'knowledge_graph.build_snapshot_30d',
        # 30d窗口随每日上新变化明显，改为每日更新（避开 04:00~05:10 顶刊任务高峰）
        'schedule': crontab(hour=6, minute=0),  # 每天 06:00
        'options': {'queue': 'knowledge_graph'},
    },

    # 模块5：知识图谱 - 预生成Top社区WiW摘要（每日，避免首位用户等待）
    'graph-precompute-wiw': {
        'task': 'knowledge_graph.precompute_wiw',
        # 等待 1d/7d/30d 快照全部生成完成后再跑
        'schedule': crontab(hour=6, minute=10),  # 每天 06:10
        'options': {'queue': 'knowledge_graph'},
    },
    
    # 模块5：知识图谱 - 180天快照（每月1日凌晨2点，UTC+8）
    'graph-build-snapshot-180d': {
        'task': 'knowledge_graph.build_snapshot_180d',
        # 180d窗口计算量较大，改为每2个月更新一次（偶数月1日 06:30）
        'schedule': crontab(hour=6, minute=30, day_of_month=1, month_of_year='2,4,6,8,10,12'),
        'options': {'queue': 'knowledge_graph'},
    },

    # 模块8：arXiv前沿 - 增量爬取（每日凌晨3点，UTC+8）
    'arxiv-incremental-crawl': {
        'task': 'arxiv.incremental_crawl',
        'schedule': crontab(hour=3, minute=0),  # UTC+8 03:00
        'options': {'queue': 'arxiv'},
    },

    # 模块8：BioRxiv前沿 - 增量爬取（每日凌晨3:30，UTC+8）
    'biorxiv-incremental-crawl': {
        'task': 'biorxiv.incremental_crawl',
        'schedule': crontab(hour=3, minute=30),  # UTC+8 03:30
        'options': {'queue': 'arxiv'},
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

# 任务级别超时/批量配置（journals 需要长时间）
celery_app.conf.task_annotations = {
    'journals_tracking.crawl_all_journals': {
        'soft_time_limit': 10800,  # 3h
        'time_limit': 14400,       # 4h
    },
    'journals_tracking.rollup_7days': {
        'soft_time_limit': 10800,
        'time_limit': 14400,
    },
    'journals_tracking.update_citation_counts': {
        'soft_time_limit': 10800,
        'time_limit': 14400,
    },
}

# Worker启动时初始化数据库连接
from celery.signals import worker_ready

@worker_ready.connect
def init_worker_db(**kwargs):
    """Worker启动时初始化数据库"""
    import asyncio
    from core.database import init_database
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(init_database())
        loop.close()
        print("✅ Celery Worker: 数据库初始化成功")
    except Exception as e:
        print(f"❌ Celery Worker: 数据库初始化失败 - {e}")
