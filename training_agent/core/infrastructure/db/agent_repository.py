"""AgentRun / AgentStep 仓储实现（基础设施层）。

实现 `core/domain/agent/repository.py` 的 `AgentRunRepository` 端口。
关键修复（#7）：每步完成后**增量**写入，不再把整段 `step_history`
列表全量重写（原 persistence 每步 UPDATE 整个 JSON，O(n²)）。

- `save_step` / `update_step`：单条 AgentStep 行，O(1)。
- `update_run`：仅更新运行标量字段，不触碰 `step_history`。
- `append_run_step_history`：以 Postgres jsonb 拼接做 O(1) 追加，
  保证 `api/routers/agent.py` 读取 `run.step_history` 仍能拿到完整历史。
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text, update

from models.tables import AgentRun, AgentStep


class AgentRunRepositoryImpl:
    """Agent 运行聚合根仓储实现。"""

    def __init__(self, db):
        # db 为异步 SQLAlchemy session（由应用层 persistence 注入）
        self._db = db

    async def save_run(self, run: AgentRun) -> AgentRun:
        """持久化新建 AgentRun，flush 后返回（含生成的 id）。"""
        self._db.add(run)
        await self._db.flush()
        return run

    async def update_run(self, run_id: UUID, **fields: object) -> None:
        """更新 AgentRun 标量字段（不触碰 step_history）。"""
        if not fields:
            return
        await self._db.execute(
            update(AgentRun).where(AgentRun.id == run_id).values(**fields)
        )

    async def save_step(self, step: AgentStep) -> AgentStep:
        """持久化新建 AgentStep，flush 后返回（含生成的 id）。"""
        self._db.add(step)
        await self._db.flush()
        return step

    async def update_step(self, step_id: UUID, **fields: object) -> None:
        """更新单条 AgentStep（O(1) 增量）。"""
        if not fields:
            return
        await self._db.execute(
            update(AgentStep).where(AgentStep.id == step_id).values(**fields)
        )

    async def append_run_step_history(self, run_id: UUID, entry: dict) -> None:
        """O(1) 追加一条 step 历史到 AgentRun.step_history（jsonb 拼接）。"""
        await self._db.execute(
            text(
                "UPDATE agent_runs "
                "SET step_history = COALESCE(step_history::jsonb, '[]'::jsonb) "
                "|| CAST(:entry AS jsonb) "
                "WHERE id = :rid"
            ),
            {"entry": json.dumps(entry, ensure_ascii=False), "rid": run_id},
        )
