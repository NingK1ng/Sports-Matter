"""
Subscription Service Tests
"""
import pytest
from modules.literature_pool.services.subscription_service import SubscriptionService
from modules.literature_pool.models.user import User


@pytest.mark.asyncio
async def test_create_subscription(db_session):
    """测试创建订阅"""
    # 创建测试用户
    user = User(
        wechat_openid="test_openid_sub_1",
        wechat_nickname="测试用户",
        login_source="wechat_open"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    service = SubscriptionService(db_session)
    
    subscription = await service.create_subscription(
        user_id=user.id,
        title="运动损伤预防",
        query_text="sports injury prevention"
    )
    
    assert subscription.id is not None
    assert subscription.user_id == user.id
    assert subscription.title == "运动损伤预防"
    assert subscription.is_active == 1


@pytest.mark.asyncio
async def test_subscription_limit(db_session):
    """测试订阅数量限制（最多3个）"""
    # 创建测试用户
    user = User(
        wechat_openid="test_openid_sub_2",
        wechat_nickname="测试用户",
        login_source="wechat_open"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    service = SubscriptionService(db_session)
    
    # 创建3个订阅
    for i in range(3):
        await service.create_subscription(
            user_id=user.id,
            title=f"订阅{i+1}",
            query_text=f"query{i+1}"
        )
    
    # 尝试创建第4个订阅，应该抛出异常
    with pytest.raises(ValueError, match="SUBSCRIPTION_LIMIT_EXCEEDED"):
        await service.create_subscription(
            user_id=user.id,
            title="订阅4",
            query_text="query4"
        )


@pytest.mark.asyncio
async def test_get_user_subscriptions(db_session):
    """测试获取用户订阅列表"""
    # 创建测试用户
    user = User(
        wechat_openid="test_openid_sub_3",
        wechat_nickname="测试用户",
        login_source="wechat_open"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    service = SubscriptionService(db_session)
    
    # 创建2个订阅
    await service.create_subscription(user_id=user.id, title="订阅1", query_text="query1")
    await service.create_subscription(user_id=user.id, title="订阅2", query_text="query2")
    
    # 获取订阅列表
    subscriptions = await service.get_user_subscriptions(user.id)
    
    assert len(subscriptions) == 2
    assert subscriptions[0].title == "订阅2"  # 按创建时间倒序


@pytest.mark.asyncio
async def test_update_subscription(db_session):
    """测试更新订阅"""
    # 创建测试用户和订阅
    user = User(
        wechat_openid="test_openid_sub_4",
        wechat_nickname="测试用户",
        login_source="wechat_open"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    service = SubscriptionService(db_session)
    subscription = await service.create_subscription(
        user_id=user.id,
        title="原标题",
        query_text="original query"
    )
    
    # 更新订阅
    updated = await service.update_subscription(
        subscription_id=subscription.id,
        user_id=user.id,
        title="新标题",
        query_text="new query"
    )
    
    assert updated.title == "新标题"
    assert updated.query_text == "new query"


@pytest.mark.asyncio
async def test_delete_subscription(db_session):
    """测试删除订阅"""
    # 创建测试用户和订阅
    user = User(
        wechat_openid="test_openid_sub_5",
        wechat_nickname="测试用户",
        login_source="wechat_open"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    service = SubscriptionService(db_session)
    subscription = await service.create_subscription(
        user_id=user.id,
        title="测试订阅",
        query_text="test query"
    )
    
    # 删除订阅
    success = await service.delete_subscription(subscription.id, user.id)
    assert success is True
    
    # 确认已删除
    subscriptions = await service.get_user_subscriptions(user.id)
    assert len(subscriptions) == 0
