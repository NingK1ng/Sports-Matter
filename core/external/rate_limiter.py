"""
速率限制器

确保API调用不超过限制
"""
import asyncio
import time
from collections import deque


class RateLimiter:
    """
    令牌桶算法实现的速率限制器
    
    Args:
        rate: 每秒允许的请求数
        burst: 突发请求数（令牌桶容量）
    """
    
    def __init__(self, rate: int = 10, burst: int = 10):
        self.rate = rate  # 每秒请求数
        self.burst = burst  # 突发容量
        self.tokens = burst  # 当前令牌数
        self.last_update = time.time()
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """
        获取一个令牌（阻塞直到有令牌可用）
        """
        async with self.lock:
            while True:
                now = time.time()
                elapsed = now - self.last_update
                
                # 补充令牌
                self.tokens = min(
                    self.burst,
                    self.tokens + elapsed * self.rate
                )
                self.last_update = now
                
                # 如果有令牌，消耗一个
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                
                # 没有令牌，等待
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)


class SlidingWindowRateLimiter:
    """
    滑动窗口速率限制器（更精确）
    
    Args:
        rate: 每秒允许的请求数
        window: 时间窗口（秒）
    """
    
    def __init__(self, rate: int = 10, window: float = 1.0):
        self.rate = rate
        self.window = window
        self.requests = deque()
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """
        获取许可（阻塞直到可以发送请求）
        """
        async with self.lock:
            now = time.time()
            
            # 移除窗口外的请求
            while self.requests and self.requests[0] < now - self.window:
                self.requests.popleft()
            
            # 如果窗口内请求数已达上限，等待
            if len(self.requests) >= self.rate:
                # 计算需要等待的时间
                oldest = self.requests[0]
                wait_time = oldest + self.window - now + 0.01  # 加10ms余量
                
                if wait_time > 0:
                    print(f"⏳ 速率限制：等待 {wait_time:.2f}秒...")
                    await asyncio.sleep(wait_time)
                    
                    # 重新检查
                    now = time.time()
                    while self.requests and self.requests[0] < now - self.window:
                        self.requests.popleft()
            
            # 记录本次请求
            self.requests.append(now)


# 全局速率限制器实例
_pubmed_rate_limiter = None


def get_pubmed_rate_limiter(rate: int = 9) -> SlidingWindowRateLimiter:
    """
    获取 PubMed 速率限制器（单例）
    
    Args:
        rate: 每秒请求数（默认9，留1个余量）
    
    Returns:
        SlidingWindowRateLimiter: 速率限制器实例
    """
    global _pubmed_rate_limiter
    if _pubmed_rate_limiter is None:
        _pubmed_rate_limiter = SlidingWindowRateLimiter(rate=rate, window=1.0)
    return _pubmed_rate_limiter
