"""
测试API端点（集成测试）
"""
import pytest
from httpx import AsyncClient, ASGITransport
from api.main import app


@pytest.mark.asyncio
async def test_get_categories():
    """测试获取学科分类列表"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/stream/categories")
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # 应该有8个学科类
    # assert len(data) == 8  # 需要先初始化数据


@pytest.mark.asyncio
async def test_get_literature():
    """测试分页检索文献"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/stream/literature?page=1&per_page=20")
    
    assert response.status_code == 200
    data = response.json()
    
    assert 'total' in data
    assert 'page' in data
    assert 'per_page' in data
    assert 'pages' in data
    assert 'items' in data
    assert isinstance(data['items'], list)


@pytest.mark.asyncio
async def test_get_literature_with_filters():
    """测试带过滤器的文献检索"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/v1/stream/literature?window=30d&sort_by=if&top_journals=true"
        )
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data['items'], list)


@pytest.mark.asyncio
async def test_get_journals():
    """测试获取期刊列表"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/stream/journals")
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_stats():
    """测试获取统计信息"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/stream/stats")
    
    assert response.status_code == 200
    data = response.json()
    
    assert 'total_literature' in data
    assert 'by_category' in data
    assert 'by_type' in data
    assert 'last_crawl' in data
