"""集中客户端模块的轻量验证（Phase 0）。

不发起真实网络连接：MinIO/Redis 构造均为惰性。仅校验符号可导入、可调用，
以及 Redis 客户端按 db 单例复用（相同 db 返回同一实例，不同 db 返回不同实例）。
"""
from core.infrastructure.minio.client import get_minio_client
from core.infrastructure.redis.client import get_redis_client


def test_infra_clients_callable():
    assert callable(get_minio_client)
    assert callable(get_redis_client)


def test_redis_client_cache_by_db():
    a = get_redis_client(db=2)
    b = get_redis_client(db=2)
    c = get_redis_client(db=3)
    # 相同 db 复用同一实例；不同 db 返回不同实例
    assert a is b
    assert a is not c
