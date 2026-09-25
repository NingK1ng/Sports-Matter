"""
外部API客户端测试
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_pubmed_search():
    """测试PubMed检索（mock）"""
    from core.external.pubmed import PubMedClient

    client = PubMedClient()

    # Mock httpx响应
    mock_response = {
        "esearchresult": {
            "idlist": ["38123456", "38123457", "38123458"]
        }
    }

    with patch.object(client, "get", return_value=mock_response):
        pmids = await client.search("basketball[Title]", retmax=10)
        assert len(pmids) == 3
        assert "38123456" in pmids


@pytest.mark.asyncio
async def test_circuit_breaker():
    """测试熔断器"""
    from core.external.base import CircuitBreaker, CircuitState

    breaker = CircuitBreaker(failure_threshold=3, timeout=1)

    # 模拟连续失败
    for i in range(3):
        try:
            breaker.call(lambda: (_ for _ in ()).throw(Exception("API Error")))
        except Exception:
            pass

    # 熔断器应该打开
    assert breaker.state == CircuitState.OPEN

    with pytest.raises(Exception, match="Circuit breaker is OPEN"):
        breaker.call(lambda: "test")


def test_cache_key_generation():
    """测试缓存键生成"""
    from core.external.base import BaseAPIClient

    client = BaseAPIClient(base_url="https://api.example.com")
    
    key1 = client._get_cache_key("/search", {"q": "test", "limit": 10})
    key2 = client._get_cache_key("/search", {"limit": 10, "q": "test"})
    
    # 相同参数应生成相同键（顺序无关）
    assert key1 == key2

    key3 = client._get_cache_key("/search", {"q": "other"})
    assert key1 != key3
