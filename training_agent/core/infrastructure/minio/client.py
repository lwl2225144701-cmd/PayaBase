"""MinIO 客户端集中管理（Phase 0 重构）。

收敛全仓散点 ``Minio(...)`` 构造。所有调用点使用同一套配置
（endpoint / 密钥 / secure），故返回进程内复用的单例，便于测试时整体替换。
"""
from functools import lru_cache

from minio import Minio

from core.config import settings


@lru_cache(maxsize=1)
def get_minio_client() -> Minio:
    """返回复用的 MinIO 客户端单例（构造不发起网络连接）。"""
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )
