"""
Literature Pool Celery Tasks
"""
from modules.literature_pool.tasks.search_tasks import (
    search_stream_articles_task,
    search_all_subscriptions_stream_task,
)
from modules.literature_pool.tasks.wiw_tasks import (
    generate_stream_wiw_task,
    generate_journals_wiw_task,
    generate_all_subscriptions_wiw_task,
)
from modules.literature_pool.tasks.cleanup_tasks import (
    cleanup_expired_mappings_task,
    cleanup_orphan_wiw_task,
)

__all__ = [
    "search_stream_articles_task",
    "search_all_subscriptions_stream_task",
    "generate_stream_wiw_task",
    "generate_journals_wiw_task",
    "generate_all_subscriptions_wiw_task",
    "cleanup_expired_mappings_task",
    "cleanup_orphan_wiw_task",
]
