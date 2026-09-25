"""
WiW结果定时清理任务

删除7天前的历史记录
"""

from datetime import datetime, timedelta
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db_session
from modules.research_gap.models.wiw import WiWResult


async def cleanup_old_wiw_results():
    """
    清理7天前的WiW结果
    
    执行频率：每天凌晨2点
    """
    seven_days_ago = datetime.now() - timedelta(days=7)
    
    async with get_db_session() as session:
        try:
            # 统计待删除记录数
            count_stmt = select(WiWResult).where(WiWResult.created_at < seven_days_ago)
            count_result = await session.execute(count_stmt)
            count = len(count_result.scalars().all())
            
            if count == 0:
                print(f"✅ 无需清理：没有7天前的WiW记录")
                return
            
            # 删除记录
            delete_stmt = delete(WiWResult).where(WiWResult.created_at < seven_days_ago)
            result = await session.execute(delete_stmt)
            await session.commit()
            
            deleted_count = result.rowcount
            print(f"✅ 清理完成：删除了{deleted_count}条7天前的WiW记录")
            
        except Exception as e:
            print(f"❌ 清理失败: {e}")
            await session.rollback()
            raise


# Celery任务装饰器（如果使用Celery）
# 如果项目中配置了Celery，取消下面注释即可
# from core.celery_app import celery_app
# 
# @celery_app.task(name="cleanup_old_wiw_results")
# def cleanup_old_wiw_results_task():
#     """Celery定时任务入口"""
#     import asyncio
#     asyncio.run(cleanup_old_wiw_results())
