"""
API v1版本路由

统一挂载所有模块的路由
"""
from fastapi import APIRouter

# 导入模块路由
from modules.literature_stream.api import router as stream_router
from modules.journals.api import router as journals_router
from modules.research_gap.api.routes import router as research_gap_router
from modules.literature_pool.api import router as literature_pool_router
from modules.assistant.api.routes import router as assistant_router
from modules.knowledge_graph.api.routes import router as knowledge_graph_router
from modules.sports_journals.api import router as sports_journals_router
from modules.arxiv.api.routes import router as arxiv_router
from modules.sports_data.api.routes import router as sports_data_router
from api.v1.routes.translate import router as translate_router
from modules.checkin.api import router as checkin_router

# 创建v1路由器
router = APIRouter()

# 注册路由（各模块内部已声明prefix）
router.include_router(stream_router)
router.include_router(journals_router)
router.include_router(research_gap_router)
router.include_router(literature_pool_router)
router.include_router(assistant_router)
router.include_router(knowledge_graph_router)  # 知识图谱路由
router.include_router(sports_journals_router)  # 运动科学期刊路由
router.include_router(arxiv_router)  # arXiv前沿路由
router.include_router(sports_data_router)  # Sports Data 模块路由
router.include_router(translate_router)  # 翻译路由
router.include_router(checkin_router)  # 每日签到路由

@router.get("/health")
async def v1_health():
    """v1 API健康检查"""
    return {"status": "ok", "api_version": "v1"}
