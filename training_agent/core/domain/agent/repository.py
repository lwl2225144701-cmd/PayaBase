"""AgentRun / AgentStep 仓储端口。

现有 core/agent/persistence.py 是过程式函数雏形（每函数各自 db.commit），
Phase 2 将改造为 AgentRunRepository 实现，统一事务边界。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from models.tables import AgentRun, AgentStep


class AgentRunRepository(Protocol):
    """Agent 运行聚合根仓储。"""

    async def save_run(self, run: AgentRun) -> AgentRun:
        """新建 AgentRun，flush 后返回（含生成的 id）。"""
        ...

    async def update_run(self, run_id: UUID, **fields: object) -> None:
        """更新 AgentRun 状态字段。"""
        ...

    async def save_step(self, step: AgentStep) -> AgentStep:
        """新建 AgentStep，flush 后返回（含生成的 id）。"""
        ...

    async def update_step(self, step_id: UUID, **fields: object) -> None:
        """更新 AgentStep 状态字段。"""
        ...
