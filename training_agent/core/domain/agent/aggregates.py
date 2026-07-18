"""Agent 领域实体（Phase 4 充实）。

聚合根：AgentRun（含 AgentStep 内部实体）。此前 AgentStep 状态判断散落在
core/agent/planner.py 与 chat_pipeline（如 `status=="failed"`），本模块收拢。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


class AgentRunStatus:
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    TERMINAL = (COMPLETED, FAILED)


@dataclass
class AgentStep:
    id: UUID
    run_id: UUID
    step_key: str
    step_type: str
    step_goal: str
    status: str = "pending"
    output: str = ""
    error: str = ""
    tool_trace: list = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def is_failed(self) -> bool:
        return self.status == "failed"

    def is_completed(self) -> bool:
        return self.status == "completed"

    def is_pending(self) -> bool:
        return self.status == "pending"

    @classmethod
    def from_orm(cls, orm) -> AgentStep:
        return cls(
            id=orm.id,
            run_id=orm.run_id,
            step_key=orm.step_key,
            step_type=orm.step_type,
            step_goal=orm.step_goal,
            status=orm.status or "pending",
            output=orm.output or "",
            error=orm.error or "",
            tool_trace=orm.tool_trace or [],
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )


@dataclass
class AgentRun:
    id: UUID
    tenant_id: UUID
    user_id: UUID
    conversation_id: UUID
    goal: str
    status: str = AgentRunStatus.RUNNING
    route: str | None = None
    current_step: str | None = None
    next_step: str | None = None
    completed_steps_summary: str = ""
    plan_snapshot: dict = field(default_factory=dict)
    step_history: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)
    last_error: str | None = None
    retry_count: int = 0
    budget_remaining: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None

    def is_terminal(self) -> bool:
        return self.status in AgentRunStatus.TERMINAL

    def is_running(self) -> bool:
        return self.status == AgentRunStatus.RUNNING

    def is_failed(self) -> bool:
        return self.status == AgentRunStatus.FAILED

    @classmethod
    def from_orm(cls, orm) -> AgentRun:
        return cls(
            id=orm.id,
            tenant_id=orm.tenant_id,
            user_id=orm.user_id,
            conversation_id=orm.conversation_id,
            goal=orm.goal,
            status=orm.status or AgentRunStatus.RUNNING,
            route=orm.route,
            current_step=orm.current_step,
            next_step=orm.next_step,
            completed_steps_summary=orm.completed_steps_summary or "",
            plan_snapshot=orm.plan_snapshot or {},
            step_history=orm.step_history or [],
            artifacts=orm.artifacts or [],
            last_error=orm.last_error,
            retry_count=orm.retry_count or 0,
            budget_remaining=orm.budget_remaining or 0,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            completed_at=orm.completed_at,
        )
