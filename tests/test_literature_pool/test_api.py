"""
Literature Pool API Integration Tests
"""
import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """测试健康检查"""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_create_subscription_api(client: AsyncClient, test_user_token):
    """测试创建订阅API"""
    response = await client.post(
        "/v1/pool/subscriptions",
        headers={"Authorization": f"Bearer {test_user_token}"},
        json={
            "title": "运动损伤",
            "query_text": "sports injury"
        }
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "运动损伤"
    assert data["query_text"] == "sports injury"
    assert "id" in data


@pytest.mark.asyncio
async def test_get_subscriptions_api(client: AsyncClient, test_user_token):
    """测试获取订阅列表API"""
    # 先创建一个订阅
    await client.post(
        "/v1/pool/subscriptions",
        headers={"Authorization": f"Bearer {test_user_token}"},
        json={"title": "测试订阅", "query_text": "test query"}
    )
    
    # 获取订阅列表
    response = await client.get(
        "/v1/pool/subscriptions",
        headers={"Authorization": f"Bearer {test_user_token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "subscriptions" in data
    assert data["total"] > 0


@pytest.mark.asyncio
async def test_get_feed_api(client: AsyncClient, test_user_token, test_subscription_id):
    """测试获取Feed流API"""
    response = await client.get(
        f"/v1/pool/feed/{test_subscription_id}",
        headers={"Authorization": f"Bearer {test_user_token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "stream_cards" in data
    assert "journals_cards" in data
    assert "journals_articles" in data


@pytest.mark.asyncio
async def test_unauthorized_access(client: AsyncClient):
    """测试未授权访问"""
    response = await client.get("/v1/pool/subscriptions")
    assert response.status_code == 422  # Missing Authorization header


@pytest.mark.asyncio
async def test_invalid_token(client: AsyncClient):
    """测试无效token"""
    response = await client.get(
        "/v1/pool/subscriptions",
        headers={"Authorization": "Bearer invalid_token_123"}
    )
    assert response.status_code == 401
