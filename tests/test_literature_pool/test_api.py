"""
Literature Pool API Integration Tests
"""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, Mock


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
        json={"title": "运动损伤", "query_text": "sports injury"},
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
        json={"title": "测试订阅", "query_text": "test query"},
    )

    # 获取订阅列表
    response = await client.get(
        "/v1/pool/subscriptions", headers={"Authorization": f"Bearer {test_user_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert "subscriptions" in data
    assert data["total"] > 0


@pytest.mark.asyncio
async def test_get_feed_api(
    client: AsyncClient, test_user_token, test_subscription_id, monkeypatch
):
    """测试获取Feed流API"""
    from modules.literature_pool.api import feed
    from modules.research_gap.services import wiw_generator

    monkeypatch.setattr(wiw_generator, "get_pubmed_client", Mock())
    monkeypatch.setattr(feed, "cache_get", AsyncMock(return_value=[]))
    response = await client.get(
        f"/v1/pool/feed/{test_subscription_id}",
        headers={"Authorization": f"Bearer {test_user_token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "stream_cards" in data
    assert "journals_cards" in data
    assert "journals_articles" in data


@pytest.mark.asyncio
async def test_public_access_without_token(client: AsyncClient):
    """没有令牌的访客可以读取自己的订阅。"""
    response = await client.get("/v1/pool/subscriptions")
    assert response.status_code == 200
    assert response.json() == {"subscriptions": [], "total": 0}
    session = await client.get("/v1/pool/auth/session")
    assert session.status_code == 200
    assert session.json()["user"]["is_guest"] is True


@pytest.mark.asyncio
async def test_invalid_token_falls_back_to_same_visitor(client: AsyncClient):
    """无效令牌回退到当前访客，不拒绝访问或创建另一个身份。"""
    before = await client.get("/v1/pool/auth/session")
    response = await client.get(
        "/v1/pool/subscriptions", headers={"Authorization": "Bearer invalid_token_123"}
    )
    assert response.status_code == 200
    assert response.json() == {"subscriptions": [], "total": 0}
    after = await client.get(
        "/v1/pool/auth/session", headers={"Authorization": "Bearer invalid_token_123"}
    )
    assert after.status_code == 200
    assert after.json()["user"] == before.json()["user"]
