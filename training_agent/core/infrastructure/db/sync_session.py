"""Worker 同步 DB 会话工厂（Phase 4 统一）。

Web 侧用异步 Session（`models/db.py::async_session`）；Celery worker 运行在
同步上下文，需独立同步 Session。此前三个 worker（`core/tasks/*.py`）各自
`create_engine(settings.sync_database_url)` + `Session(engine)` + `engine.dispose()`
——每个任务新建连接池、结束后销毁，既泄漏连接又无法复用连接池。

本模块提供**进程级单例同步 engine** + 工厂函数，所有 worker 复用同一连接池。
SQL 语义完全不变（仍执行原生 `text()`），仅统一会话生命周期管理。
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.config import settings

# 进程级单例 engine：懒初始化，连接池跨任务复用
_engine = None


def get_sync_engine():
    global _engine
    if _engine is None:
        # pool_pre_ping 检测失效连接，避免 Celery 长驻进程拿到死连接
        _engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    return _engine


@contextmanager
def get_sync_session() -> Iterator[Session]:
    """会话上下文管理器，等价于原 `with Session(engine) as db:`。"""
    session = Session(get_sync_engine())
    try:
        yield session
    finally:
        session.close()
