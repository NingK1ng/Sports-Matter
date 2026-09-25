"""
Redis缓存模块

提供异步Redis客户端和缓存抽象层
"""

import zstandard as zstd
from typing import Any, Optional

import orjson
from redis.asyncio import Redis, ConnectionPool
from redis.exceptions import RedisError

from core.config import settings


class CacheConnectionError(Exception):
    """缓存连接错误"""

    pass


# 全局Redis客户端
_redis_client: Redis | None = None
_connection_pool: ConnectionPool | None = None


async def init_cache() -> None:
    """
    初始化Redis缓存

    创建连接池和Redis客户端

    Raises:
        CacheConnectionError: Redis连接失败
    """
    global _redis_client, _connection_pool

    if _redis_client is not None:
        return  # 已初始化

    try:
        # 创建连接池
        _connection_pool = ConnectionPool.from_url(
            settings.redis_url,
            password=settings.redis_password,
            max_connections=settings.redis_max_connections,
            socket_timeout=5,
            socket_connect_timeout=5,
            decode_responses=False,  # 使用bytes，便于压缩
        )

        # 创建Redis客户端
        _redis_client = Redis(connection_pool=_connection_pool)

        # 测试连接
        await _redis_client.ping()

        print("✅ Redis缓存初始化成功")
        print(f"   URL: {settings.redis_url}")
        print(f"   Max Connections: {settings.redis_max_connections}")

    except RedisError as e:
        print(f"❌ Redis连接失败: {e}")
        raise CacheConnectionError(f"Failed to connect to Redis: {e}")


async def close_cache() -> None:
    """
    关闭Redis连接

    释放所有连接资源
    """
    global _redis_client, _connection_pool

    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None

    if _connection_pool is not None:
        await _connection_pool.disconnect()
        _connection_pool = None

    print("👋 Redis缓存已关闭")


def get_redis() -> Redis:
    """
    获取Redis客户端

    Returns:
        Redis: Redis客户端

    Raises:
        RuntimeError: Redis未初始化
    """
    if _redis_client is None:
        raise RuntimeError("Redis not initialized. Call init_cache() first.")
    return _redis_client


def _serialize(value: Any) -> bytes:
    """
    序列化值

    使用orjson序列化，>64KB时启用zstd压缩

    Args:
        value: 要序列化的值

    Returns:
        bytes: 序列化后的字节流
    """
    # 使用orjson序列化（高性能）
    data = orjson.dumps(value)

    # 如果数据>64KB，启用zstd压缩
    if len(data) > 65536:
        compressor = zstd.ZstdCompressor()
        data = b"ZSTD:" + compressor.compress(data)

    return data


def _deserialize(data: bytes) -> Any:
    """
    反序列化值

    自动检测是否压缩并解压

    Args:
        data: 序列化的字节流

    Returns:
        Any: 反序列化后的值
    """
    # 检查是否压缩
    if data.startswith(b"ZSTD:"):
        decompressor = zstd.ZstdDecompressor()
        data = decompressor.decompress(data[5:])

    # 使用orjson反序列化
    return orjson.loads(data)


async def cache_set(
    key: str,
    value: Any,
    ttl: Optional[int] = None,
) -> bool:
    """
    设置缓存

    Args:
        key: 缓存键
        value: 缓存值（支持任意可JSON序列化的类型）
        ttl: 过期时间（秒），None表示永不过期

    Returns:
        bool: 是否成功

    Example:
        await cache_set("user:123", {"name": "Alice"}, ttl=300)
    """
    try:
        redis = get_redis()
        data = _serialize(value)
        await redis.set(key, data, ex=ttl)
        return True
    except Exception as e:
        print(f"⚠️ 缓存写入失败: {key}, {e}")
        return False


async def cache_get(key: str) -> Optional[Any]:
    """
    获取缓存

    Args:
        key: 缓存键

    Returns:
        Optional[Any]: 缓存值，不存在返回None

    Example:
        user = await cache_get("user:123")
        if user is None:
            user = await fetch_from_database(123)
            await cache_set("user:123", user, ttl=300)
    """
    try:
        redis = get_redis()
        data = await redis.get(key)
        if data is None:
            return None
        return _deserialize(data)
    except Exception as e:
        print(f"⚠️ 缓存读取失败: {key}, {e}")
        return None


async def cache_delete(key: str) -> bool:
    """
    删除缓存

    Args:
        key: 缓存键

    Returns:
        bool: 是否成功
    """
    try:
        redis = get_redis()
        await redis.delete(key)
        return True
    except Exception as e:
        print(f"⚠️ 缓存删除失败: {key}, {e}")
        return False


async def cache_exists(key: str) -> bool:
    """
    检查缓存是否存在

    Args:
        key: 缓存键

    Returns:
        bool: 是否存在
    """
    try:
        redis = get_redis()
        return await redis.exists(key) > 0
    except Exception as e:
        print(f"⚠️ 缓存检查失败: {key}, {e}")
        return False


async def cache_ttl(key: str) -> int:
    """
    获取缓存剩余过期时间

    Args:
        key: 缓存键

    Returns:
        int: 剩余秒数，-1表示永不过期，-2表示不存在
    """
    try:
        redis = get_redis()
        return await redis.ttl(key)
    except Exception as e:
        print(f"⚠️ 获取TTL失败: {key}, {e}")
        return -2


async def cache_clear_pattern(pattern: str) -> int:
    """
    按模式删除缓存

    Args:
        pattern: 键模式（支持*通配符）

    Returns:
        int: 删除的键数量

    Example:
        # 删除所有user:*键
        count = await cache_clear_pattern("user:*")
    """
    try:
        redis = get_redis()
        keys = await redis.keys(pattern)
        if keys:
            return await redis.delete(*keys)
        return 0
    except Exception as e:
        print(f"⚠️ 批量删除失败: {pattern}, {e}")
        return 0
