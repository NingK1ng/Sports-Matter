"""
Cleanup Tasks - 清理任务

定时清理过期映射和孤儿WiW
"""
from celery import shared_task

from core.database import get_db_session
from modules.literature_pool.services.wiw_service import WiWService


@shared_task(name="literature_pool.cleanup_expired_mappings")
def cleanup_expired_mappings_task() -> dict:
    """
    清理过期映射任务（每日凌晨1点）
    
    删除expires_at < NOW() - 7天的映射记录
    
    Returns:
        任务结果
    """
    import asyncio
    
    async def _run():
        async with get_db_session() as session:
            wiw_service = WiWService(session)
            deleted_count = await wiw_service.cleanup_expired_mappings(days=7)
            
            return {
                "status": "success",
                "deleted_mappings": deleted_count
            }
    
    return asyncio.run(_run())


@shared_task(name="literature_pool.cleanup_orphan_wiw")
def cleanup_orphan_wiw_task() -> dict:
    """
    清理孤儿WiW任务（每周一凌晨2点）
    
    删除90天内未被任何pool_wiw_cards引用的wiw_results记录
    
    Returns:
        任务结果
    """
    import asyncio
    
    async def _run():
        async with get_db_session() as session:
            wiw_service = WiWService(session)
            deleted_count = await wiw_service.cleanup_orphan_wiw_results(days=90)
            
            return {
                "status": "success",
                "deleted_wiw_results": deleted_count
            }
    
    return asyncio.run(_run())
