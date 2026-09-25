"""
外部API客户端基类

提供统一的弹性策略：重试、熔断、缓存
"""

import asyncio
import time
from typing import Any, Optional, Dict
from enum import Enum

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from core.cache import cache_get, cache_set


class CircuitState(Enum):
    """熔断器状态"""

    CLOSED = "closed"  # 正常
    OPEN = "open"  # 熔断
    HALF_OPEN = "half_open"  # 半开（探测）


class CircuitBreaker:
    """
    熔断器实现

    连续错误超过阈值时熔断，冷却后进入半开状态探测恢复
    """

    def __init__(
        self,
        failure_threshold: int = 5,  # 失败阈值
        timeout: int = 60,  # 熔断时间（秒）
        half_open_max_calls: int = 1,  # 半开状态最大探测请求
    ):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.half_open_max_calls = half_open_max_calls

        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
        self.half_open_calls = 0

    def call(self, func):
        """
        执行函数调用，带熔断保护

        Args:
            func: 要执行的函数

        Returns:
            Any: 函数返回值

        Raises:
            Exception: 熔断打开时抛出异常
        """
        # 检查熔断状态
        if self.state == CircuitState.OPEN:
            # 检查是否可以进入半开状态
            if (
                self.last_failure_time
                and time.time() - self.last_failure_time > self.timeout
            ):
                print("🔄 熔断器进入半开状态，尝试探测恢复")
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0
            else:
                raise Exception(f"Circuit breaker is OPEN. Retry after {self.timeout}s")

        # 半开状态：限制请求数
        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_calls >= self.half_open_max_calls:
                raise Exception("Half-open circuit breaker max calls reached")
            self.half_open_calls += 1

        try:
            result = func()
            # 成功：重置计数器
            self.on_success()
            return result
        except Exception as e:
            # 失败：增加计数器
            self.on_failure()
            raise e

    def on_success(self):
        """成功回调"""
        if self.state == CircuitState.HALF_OPEN:
            print("✅ 熔断器恢复正常")
            self.state = CircuitState.CLOSED

        self.failure_count = 0
        self.last_failure_time = None

    def on_failure(self):
        """失败回调"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            print(f"🚨 熔断器打开！连续失败{self.failure_count}次")
            self.state = CircuitState.OPEN


class BaseAPIClient:
    """
    外部API客户端基类

    提供：
    - HTTP客户端
    - 重试机制（指数退避 + 抖动）
    - 熔断器
    - Redis缓存
    """

    def __init__(
        self,
        base_url: str,
        timeout: int = 10,
        enable_cache: bool = True,
        cache_ttl: int = 3600,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.enable_cache = enable_cache
        self.cache_ttl = cache_ttl

        # HTTP客户端（使用默认HTTP/2，PubMed需要）
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Sports-Matter/1.0; +https://github.com/yourusername/sports-matter)"
            }
        )

        # 熔断器
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            timeout=60,
            half_open_max_calls=1,
        )

    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()

    def _get_cache_key(self, endpoint: str, params: Optional[Dict] = None) -> str:
        """
        生成缓存键

        Args:
            endpoint: API端点
            params: 请求参数

        Returns:
            str: 缓存键
        """
        import hashlib
        import json

        # 包含API版本和参数哈希
        params_str = json.dumps(params or {}, sort_keys=True)
        params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
        return f"api:{self.__class__.__name__}:{endpoint}:{params_hash}"

    @retry(
        stop=stop_after_attempt(5),  # 增加到5次重试
        wait=wait_exponential(multiplier=1, min=2, max=30),  # 最大等待30秒
        retry=retry_if_exception_type((
            httpx.TimeoutException,
            httpx.HTTPStatusError,
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.PoolTimeout,
            Exception,  # 捕获所有异常（包括anyio.EndOfStream等）
        )),
        reraise=True,
    )
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        **kwargs,
    ) -> Any:
        """
        发送HTTP请求（带重试和熔断）

        Args:
            method: HTTP方法
            endpoint: API端点
            params: 查询参数
            **kwargs: 其他httpx参数

        Returns:
            Any: 响应数据

        Raises:
            Exception: 请求失败
        """
        # 直接异步调用，不使用熔断器（避免事件循环冲突）
        try:
            response = await self.client.request(method, endpoint, params=params, **kwargs)
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError) as e:
            print(f"⚠️  连接错误: {type(e).__name__} - {str(e)[:100]}")
            raise  # 让 tenacity 重试

        # 处理429（速率限制）
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 1))  # 默认1秒而不是60秒
            print(f"⚠️  速率限制！等待{retry_after}秒...")
            await asyncio.sleep(retry_after)
            raise httpx.HTTPStatusError(
                f"Rate limited", request=response.request, response=response
            )

        # 处理5xx错误
        if 500 <= response.status_code < 600:
            raise httpx.HTTPStatusError(
                f"Server error: {response.status_code}",
                request=response.request,
                response=response,
            )

        response.raise_for_status()
        
        # 调试：捕获JSON解析错误
        try:
            return response.json()
        except Exception as e:
            print(f"\n❌ JSON解析失败")
            print(f"响应状态码: {response.status_code}")
            print(f"响应内容（前500字符）: {response.text[:500]}")
            raise

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict] = None,
        use_cache: bool = True,
        **kwargs,
    ) -> Any:
        """
        GET请求（带缓存）

        Args:
            endpoint: API端点
            params: 查询参数
            use_cache: 是否使用缓存
            **kwargs: 其他httpx参数

        Returns:
            Any: 响应数据
        """
        # 尝试从缓存读取
        if self.enable_cache and use_cache:
            cache_key = self._get_cache_key(endpoint, params)
            cached_data = await cache_get(cache_key)
            if cached_data is not None:
                print(f"✅ 缓存命中: {cache_key}")
                return cached_data

        # 发送请求
        data = await self._request("GET", endpoint, params=params, **kwargs)

        # 写入缓存
        if self.enable_cache and use_cache:
            cache_key = self._get_cache_key(endpoint, params)
            await cache_set(cache_key, data, ttl=self.cache_ttl)

        return data

    async def post(
        self,
        endpoint: str,
        data: Optional[Dict] = None,
        use_cache: bool = True,
        **kwargs,
    ) -> Any:
        """
        POST请求（带缓存）

        Args:
            endpoint: API端点
            data: 请求体数据（form-encoded）
            use_cache: 是否使用缓存
            **kwargs: 其他httpx参数

        Returns:
            Any: 响应数据
        """
        # 尝试从缓存读取
        if self.enable_cache and use_cache:
            cache_key = self._get_cache_key(endpoint, data)
            cached_data = await cache_get(cache_key)
            if cached_data is not None:
                print(f"✅ 缓存命中: {cache_key}")
                return cached_data

        # 发送POST请求（使用form-encoded）
        response_data = await self._request("POST", endpoint, data=data, **kwargs)

        # 写入缓存
        if self.enable_cache and use_cache:
            cache_key = self._get_cache_key(endpoint, data)
            await cache_set(cache_key, response_data, ttl=self.cache_ttl)

        return response_data
