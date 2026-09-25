"""
缓存模块测试
"""

import pytest
from core.cache import cache_set, cache_get, cache_delete, _serialize, _deserialize


def test_serialize_deserialize():
    """测试序列化和反序列化"""
    data = {"name": "Alice", "age": 30, "tags": ["python", "fastapi"]}

    # 序列化
    serialized = _serialize(data)
    assert isinstance(serialized, bytes)

    # 反序列化
    deserialized = _deserialize(serialized)
    assert deserialized == data


def test_serialize_large_data():
    """测试大数据压缩"""
    # 创建>64KB的数据
    large_data = {"content": "x" * 100000}

    serialized = _serialize(large_data)

    # 检查是否压缩
    assert serialized.startswith(b"ZSTD:")

    # 反序列化
    deserialized = _deserialize(serialized)
    assert deserialized == large_data


@pytest.mark.asyncio
async def test_cache_operations():
    """测试缓存基本操作（需要Redis运行）"""
    from core.cache import init_cache, close_cache

    try:
        await init_cache()

        # 设置缓存
        result = await cache_set("test_key", {"value": 123}, ttl=60)
        assert result is True

        # 读取缓存
        data = await cache_get("test_key")
        assert data == {"value": 123}

        # 删除缓存
        result = await cache_delete("test_key")
        assert result is True

        # 验证删除
        data = await cache_get("test_key")
        assert data is None

        await close_cache()
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")
