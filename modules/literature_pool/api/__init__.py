"""
Literature Pool API Routes
"""
from fastapi import APIRouter
from modules.literature_pool.api import auth, subscriptions, feed, payments
from modules.literature_pool.api import dev

# 创建主路由
router = APIRouter(prefix="/pool", tags=["Literature Pool"])

# 注册子路由
router.include_router(auth.router)
router.include_router(subscriptions.router)
router.include_router(feed.router)
router.include_router(payments.router)
router.include_router(dev.router)

__all__ = ["router"]
