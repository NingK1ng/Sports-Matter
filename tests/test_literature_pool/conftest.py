"""
Test Fixtures for Literature Pool
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from httpx import AsyncClient

from api.main import app
from core.database import get_db
from modules.literature_pool.models.user import User
from modules.literature_pool.models.subscription import PoolSubscription
from modules.literature_pool.services.auth_service import AuthService


@pytest.fixture
async def db_session():
    """创建测试数据库会话"""
    # 使用内存SQLite数据库
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    # 创建表（这里需要导入所有models）
    async with engine.begin() as conn:
        from models.base import Base
        await conn.run_sync(Base.metadata.create_all)
    
    async with async_session() as session:
        yield session
    
    await engine.dispose()


@pytest.fixture
async def test_user(db_session: AsyncSession):
    """创建测试用户"""
    user = User(
        wechat_openid="test_openid_fixture",
        wechat_nickname="测试用户",
        login_source="wechat_open"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_user_token(db_session: AsyncSession, test_user):
    """创建测试用户的JWT token"""
    auth_service = AuthService(db_session)
    token = auth_service.create_jwt_token(test_user.id)
    return token


@pytest.fixture
async def test_subscription(db_session: AsyncSession, test_user):
    """创建测试订阅"""
    subscription = PoolSubscription(
        user_id=test_user.id,
        title="测试订阅",
        query_text="test query",
        is_active=1
    )
    db_session.add(subscription)
    await db_session.commit()
    await db_session.refresh(subscription)
    return subscription


@pytest.fixture
async def test_subscription_id(test_subscription):
    """返回测试订阅ID"""
    return test_subscription.id


@pytest.fixture
async def client(app):
    """HTTP客户端"""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
