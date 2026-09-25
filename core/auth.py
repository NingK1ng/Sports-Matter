"""
认证与授权模块（占位实现）

阶段1返回固定测试用户，阶段3由其他团队实现完整JWT认证
"""

from typing import Optional
from fastapi import Request


class User:
    """用户模型（占位）"""

    def __init__(self, user_id: str, username: str, email: Optional[str] = None):
        self.user_id = user_id
        self.username = username
        self.email = email

    def dict(self):
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
        }


async def get_current_user(
    request: Request,
    token: Optional[str] = None,
) -> User:
    """
    获取当前用户（占位实现）

    阶段1：返回固定测试用户 demo-user
    阶段3：实现真实JWT认证

    Args:
        request: FastAPI请求对象
        token: JWT Token（当前未使用）

    Returns:
        User: 用户对象

    Example:
        from fastapi import Depends
        from core.auth import get_current_user

        @app.get("/me")
        async def get_me(user: User = Depends(get_current_user)):
            return user.dict()
    """
    # 阶段1：固定返回测试用户
    print("⚠️  使用占位认证：demo-user")

    return User(
        user_id="demo-user",
        username="Demo User",
        email="demo@sportsmatter.local",
    )


# TODO: 阶段3实现以下功能
# - def create_access_token(data: dict) -> str:
# - def verify_token(token: str) -> dict:
# - async def require_auth(token: str = Depends(oauth2_scheme)) -> User:
# - async def require_permission(user: User, permission: str) -> bool:
