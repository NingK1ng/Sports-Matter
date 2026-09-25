"""
FastAPI应用入口

提供统一的API网关和中间件配置
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import make_asgi_app

from core.config import settings

# 导入v1路由（后续实现）
# from api.v1 import router as v1_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    应用生命周期管理

    启动时初始化资源，关闭时清理资源
    """
    from core.database import init_database, close_database
    from core.cache import init_cache, close_cache

    # 启动时
    print(f"🚀 {settings.app_name} v{settings.app_version} 启动中...")
    print(f"📝 环境: {settings.app_env}")
    print(f"🔧 调试模式: {settings.debug}")

    # 初始化数据库连接池
    await init_database()

    # 初始化Redis连接（可选，阶段A可跳过）
    try:
        await init_cache()
    except Exception as e:
        print(f"⚠️  Redis初始化失败（可选服务，阶段A不影响功能）: {e}")

    # 初始化Milvus连接（未来WiW Agent模块使用，当前阶段跳过）
    # Milvus暂时禁用（marshmallow版本冲突问题，待WiW Agent模块实施时修复）
    # try:
    #     from core.milvus import init_milvus
    #     init_milvus(host="localhost", port=19530)
    # except Exception as e:
    #     print(f"⚠️  Milvus初始化失败（可选服务）: {e}")

    yield

    # 关闭时
    print("👋 应用正在关闭...")
    await close_database()
    try:
        await close_cache()
    except:
        pass
    # Milvus暂时禁用
    # try:
    #     from core.milvus import close_milvus
    #     close_milvus()
    # except:
    #     pass


# 创建FastAPI应用
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="运动科学文献信息平台API",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
    lifespan=lifespan,
)

# ==========================================
# 中间件配置
# ==========================================

# CORS中间件（开发环境允许所有来源）
cors_origins = settings.allowed_origins_list
try:
    if settings.app_env.lower() in ["development", "dev", "local"]:
        # 开发环境允许所有来源（包括file://协议）
        cors_origins = ["*"]
except Exception:
    pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"] if cors_origins == ["*"] else cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=600,  # 预检请求缓存10分钟
)

# Gzip压缩中间件（响应>16KB时启用）
app.add_middleware(GZipMiddleware, minimum_size=16384)


# ==========================================
# 请求日志中间件
# ==========================================
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    记录所有HTTP请求

    包含：request_id, route, method, status, cost_ms
    """
    import time
    import uuid

    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start_time = time.time()

    # 将request_id注入到state
    request.state.request_id = request_id

    response = await call_next(request)

    # 计算耗时
    cost_ms = int((time.time() - start_time) * 1000)

    # 添加响应头
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{cost_ms}ms"

    # 记录日志
    print(
        f"📊 {request.method} {request.url.path} | "
        f"Status: {response.status_code} | "
        f"Time: {cost_ms}ms | "
        f"ID: {request_id}"
    )

    return response


# ==========================================
# 全局异常处理
# ==========================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    捕获所有未处理的异常

    返回统一格式的错误响应
    """
    request_id = getattr(request.state, "request_id", "unknown")

    # 记录错误日志
    print(f"❌ 全局异常: {type(exc).__name__}: {str(exc)}")
    print(f"   Request ID: {request_id}")
    print(f"   Path: {request.method} {request.url.path}")

    # 根据环境返回不同的错误信息
    error_detail = str(exc) if settings.debug else "Internal server error"

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "E500_INTERNAL",
                "message": "服务器内部错误",
                "detail": error_detail,
            },
            "meta": {"request_id": request_id},
        },
    )


# ==========================================
# 健康检查端点
# ==========================================
@app.get("/health", tags=["系统"])
async def health_check():
    """
    健康检查端点

    Returns:
        dict: 健康状态
    """
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version}


@app.get("/", tags=["系统"])
async def root():
    """
    根路径

    Returns:
        dict: 欢迎信息
    """
    return {
        "message": f"欢迎使用 {settings.app_name}",
        "version": settings.app_version,
        "docs": "/docs" if settings.debug else "Documentation disabled in production",
    }


# ==========================================
# Prometheus指标端点
# ==========================================
# 仅在开发/staging环境暴露
if settings.app_env in ["development", "staging"]:
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)


# ==========================================
# 注册v1路由
# ==========================================
from api.v1 import router as v1_router
app.include_router(v1_router, prefix="/v1")
# 兼容前端默认 `/api/v1` 前缀（生产环境无Vite代理时不再404）
app.include_router(v1_router, prefix="/api/v1")


# ==========================================
# 挂载静态文件（前端）- 支持SPA路由
# ==========================================
from fastapi.responses import FileResponse

# 获取项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

# 挂载前端静态文件（优先使用生产构建目录 dist）
if FRONTEND_DIR.exists():
    dist_dir = FRONTEND_DIR / "dist"
    if dist_dir.exists():
        # 挂载静态资源（assets）
        app.mount("/frontend/assets", StaticFiles(directory=str(dist_dir / "assets")), name="frontend-assets")
        
        # 所有 /frontend/* 路由返回 index.html（支持SPA路由）
        # 但排除特定静态文件（如worker.js）
        @app.get("/frontend/{full_path:path}")
        async def serve_frontend(full_path: str):
            """服务前端SPA应用"""
            # 特殊处理：直接返回静态文件（如worker）
            if full_path.endswith('.js') or full_path.endswith('.json') or full_path.endswith('.wasm'):
                file_path = dist_dir / full_path
                if file_path.exists() and file_path.is_file():
                    return FileResponse(file_path)
            
            # 默认返回index.html（React Router处理）
            index_path = dist_dir / "index.html"
            if index_path.exists():
                return FileResponse(index_path)
            return {"error": "Frontend not found"}
        
        print(f"✅ 前端静态文件已挂载（SPA模式）: {dist_dir}")
    else:
        print(f"⚠️  前端构建目录不存在: {dist_dir}")
else:
    print(f"⚠️  前端目录不存在: {FRONTEND_DIR}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
