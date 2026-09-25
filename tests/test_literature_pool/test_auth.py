"""
Auth Service Tests
"""
import pytest
from unittest.mock import AsyncMock, patch
from modules.literature_pool.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_generate_wechat_qr_url(db_session):
    """测试生成微信二维码URL"""
    service = AuthService(db_session)
    state = "test_state_123"
    
    url = service.generate_wechat_qr_url(state)
    
    assert "https://open.weixin.qq.com/connect/qrconnect" in url
    assert f"state={state}" in url
    assert "appid=" in url
    assert "redirect_uri=" in url
    assert "scope=snsapi_login" in url


@pytest.mark.asyncio
async def test_create_jwt_token(db_session):
    """测试创建JWT token"""
    service = AuthService(db_session)
    user_id = 123
    
    token = service.create_jwt_token(user_id)
    
    assert isinstance(token, str)
    assert len(token) > 0
    
    # 验证token
    verified_user_id = service.verify_jwt_token(token)
    assert verified_user_id == user_id


@pytest.mark.asyncio
async def test_verify_invalid_jwt_token(db_session):
    """测试验证无效的JWT token"""
    service = AuthService(db_session)
    
    result = service.verify_jwt_token("invalid_token_123")
    
    assert result is None


@pytest.mark.asyncio
async def test_get_or_create_user_new_user(db_session):
    """测试创建新用户"""
    service = AuthService(db_session)
    
    user = await service.get_or_create_user(
        openid="test_openid_123",
        unionid="test_unionid_123",
        nickname="测试用户",
        avatar="https://example.com/avatar.jpg"
    )
    
    assert user.id is not None
    assert user.wechat_openid == "test_openid_123"
    assert user.wechat_nickname == "测试用户"
    assert user.last_login_at is not None


@pytest.mark.asyncio
async def test_get_or_create_user_existing_user(db_session):
    """测试获取已存在的用户"""
    service = AuthService(db_session)
    
    # 第一次创建
    user1 = await service.get_or_create_user(
        openid="test_openid_456",
        unionid=None,
        nickname="用户1",
        avatar="https://example.com/avatar1.jpg"
    )
    
    # 第二次获取
    user2 = await service.get_or_create_user(
        openid="test_openid_456",
        unionid=None,
        nickname="用户2",  # 昵称更新
        avatar="https://example.com/avatar2.jpg"
    )
    
    assert user1.id == user2.id
    assert user2.wechat_nickname == "用户2"  # 昵称已更新
