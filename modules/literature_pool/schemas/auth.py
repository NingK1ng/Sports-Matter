"""
Auth API Schemas
"""
from pydantic import BaseModel


class WeChatLoginResponse(BaseModel):
    """微信登录响应"""
    qr_url: str


class WeChatCallbackRequest(BaseModel):
    """微信回调请求"""
    code: str
    state: str


class TokenResponse(BaseModel):
    """Token响应"""
    access_token: str
    token_type: str = "bearer"
    user_id: int
    nickname: str
    avatar: str


class InviteRedeemRequest(BaseModel):
    """邀请码兑换请求"""
    code: str
