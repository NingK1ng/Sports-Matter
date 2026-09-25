"""
文献流 - IF 导入与回填 Celery 任务
- import_if_from_excel: 从Excel导入/更新 journal_metadata.if_5y
- enrich_if_recent: 抓取后对近期文献做 IF5 回填，确保前端能显示
"""
from __future__ import annotations

from celery import shared_task
from typing import Dict, Any

from core.database import get_db_session, init_database
from modules.literature_stream.services.if_importer import import_if_from_excel, enrich_if_for_recent


@shared_task(name="literature_stream.import_if_from_excel")
def import_if_from_excel_task() -> Dict[str, Any]:
    """从Excel导入/更新 IF 映射（journal_metadata）。"""
    async def _run():
        await init_database()
        async with get_db_session() as db:
            upserts = await import_if_from_excel(db)
            return {"upserts": upserts}

    import asyncio
    return asyncio.run(_run())


@shared_task(name="literature_stream.enrich_if_recent")
def enrich_if_recent_task(days: int = 90) -> Dict[str, Any]:
    """回填近期文献（默认90天）IF5 字段。"""
    async def _run():
        await init_database()
        async with get_db_session() as db:
            updated = await enrich_if_for_recent(db, days=days)
            return {"updated": updated, "days": days}

    import asyncio
    return asyncio.run(_run())
