"""Redis 客户端集中管理（Phase 0 重构）。

收敛散点 ``redis.Redis(...)`` 构造。不同业务使用不同 db
（intent 缓存 = db 2，rerank 缓存 = db 3），故以 db 为缓存键复用实例。
"""
from functools import lru_cache

import redis

from core.config import settings


@lru_cache(maxsize=8)
def get_redis_client(db: int = 0) -> "redis.Redis":
    """返回指定 db 的 Redis 客户端（按 db 缓存复用，构造不发起连接）。"""
    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=db,
        decode_responses=True,
    )
