"""Compatibility import: every producer and worker uses the same Celery app."""
from core.queue import celery_app

__all__ = ["celery_app"]
