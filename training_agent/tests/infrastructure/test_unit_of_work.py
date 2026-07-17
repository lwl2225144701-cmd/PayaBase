"""UnitOfWork 事务语义测试。

验证：
1. 正常退出 with 块 → commit
2. 异常退出 with 块 → rollback
3. 各 Repository 正确挂载
4. 手动 commit/rollback 可调用
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.infrastructure.db.unit_of_work import UnitOfWork


@pytest.mark.asyncio
async def test_uow_commit_on_success():
    """正常退出 with 块时自动 commit，不 rollback。"""
    session = AsyncMock()
    async with UnitOfWork(session):
        pass  # 正常退出
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_uow_rollback_on_exception():
    """异常退出 with 块时自动 rollback，不 commit。"""
    session = AsyncMock()
    with pytest.raises(ValueError, match="boom"):
        async with UnitOfWork(session):
            raise ValueError("boom")
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_uow_repositories_attached():
    """UoW 挂载全部 6 个 Repository。"""
    session = AsyncMock()
    uow = UnitOfWork(session)
    for attr in ("knowledge_bases", "documents", "chunks",
                 "conversations", "messages", "agent_runs"):
        assert hasattr(uow, attr), f"UoW 缺少 Repository: {attr}"


@pytest.mark.asyncio
async def test_uow_manual_commit_rollback():
    """手动 commit/rollback 可调用。"""
    session = AsyncMock()
    uow = UnitOfWork(session)
    await uow.commit()
    session.commit.assert_awaited_once()
    await uow.rollback()
    session.rollback.assert_awaited_once()
