"""Serialize expensive scheduled tasks without waiting in a worker slot."""
from contextlib import contextmanager
from uuid import uuid4
from redis import Redis
from core.config import settings


@contextmanager
def task_lock(name: str, ttl: int = 1900):
    client = Redis.from_url(settings.redis_url, password=settings.redis_password,
                            socket_timeout=5, socket_connect_timeout=5)
    token = uuid4().hex
    key = f"sm:task-lock:{name}"
    acquired = False
    try:
        acquired = bool(client.set(key, token, ex=ttl, nx=True))
        yield acquired
    finally:
        if acquired:
            client.eval("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end", 1, key, token)
        client.close()
