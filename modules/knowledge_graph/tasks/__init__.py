"""知识图谱Celery任务"""
from .snapshot_tasks import (
    build_snapshot_1d,
    build_snapshot_7d,
    build_snapshot_30d,
    build_snapshot_180d,
)

__all__ = [
    'build_snapshot_1d',
    'build_snapshot_7d',
    'build_snapshot_30d',
    'build_snapshot_180d',
]
