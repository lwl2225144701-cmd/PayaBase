"""Agent 持久化 service:只负责 AgentRun / AgentStep 的 CRUD（应用层门面）。

不负责:
  - LLM 调用 / Tool 执行 / SSE 输出 / RAG 检索 / PPT/PDF 生成 / KB miss

设计原则:
  - 失败非致命:logger.warning + rollback,不抛异常,不阻断主流程
  - 不感知 SSE / 前端返回格式
  - 不感知 chat_pipeline 的大状态对象(ChatRuntimeState)

增量写入（修复 #7）：每步完成后只 UPDATE 单条 AgentStep 行 + UPDATE AgentRun
标量字段 + 以 jsonb 拼接**追加**一条 step 历史，不再把整段 step_history 全量重写
（原实现每步 UPDATE 整个 JSON 列表，O(n²)）。
真实 SQL 下沉到 `core/infrastructure/db/agent_repository.py`（实现领域层端口）。
"""

import logging
import uuid as _uuid
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from core.infrastructure.db.agent_repository import AgentRunRepositoryImpl
from models.tables import AgentRun, AgentStep

logger = logging.getLogger(__name__)


@dataclass
class AgentPersistenceIds:
    """数据库主键包,替代 chat_pipeline 中散落的三个变量。"""

    run_db_id: UUID | None = None
    step_db_id: UUID | None = None
    finalize_step_db_id: UUID | None = None


def _build_step_history_entry(agent_step_state) -> dict:
    """构造与 AgentRunState.add_step_result 一致的历史条目（截断规则相同）。"""
    output = (agent_step_state.output or "")[:500]
    error = (agent_step_state.error or "")[:500]
    tool_trace = (agent_step_state.tool_trace or [])[-10:]
    return {
        "step_id": agent_step_state.step_id,
        "step_type": agent_step_state.step_type,
        "step_goal": agent_step_state.step_goal,
        "status": agent_step_state.status,
        "output": output,
        "error": error,
        "tool_trace": tool_trace,
    }


_TERMINAL_STATUSES = {"completed", "failed", "stopped"}


async def persist_initial_agent_run(
    *,
    db,
    tenant_id: str,
    user_id: str,
    conversation_id,
    route: str,
    agent_run_state,
    agent_step_state,
) -> AgentPersistenceIds:
    """创建 AgentRun + 第一条 AgentStep,返回数据库主键。

    失败时 logger.warning + rollback,返回空 AgentPersistenceIds(),不抛异常。
    """
    ids = AgentPersistenceIds()
    try:
        repo = AgentRunRepositoryImpl(db)
        run_row = AgentRun(
            tenant_id=_uuid.UUID(tenant_id),
            user_id=_uuid.UUID(user_id),
            conversation_id=conversation_id,
            goal=agent_run_state.goal,
            status=agent_run_state.status,
            route=route,
            current_step=agent_run_state.current_step,
            next_step=agent_run_state.next_step,
            completed_steps_summary=agent_run_state.completed_steps_summary,
            plan_snapshot=agent_run_state.plan_snapshot,
            step_history=agent_run_state.step_history,
            artifacts=agent_run_state.artifacts,
            last_error=agent_run_state.last_error or None,
            retry_count=agent_run_state.retry_count,
            budget_remaining=agent_run_state.budget_remaining,
        )
        await repo.save_run(run_row)
        ids.run_db_id = run_row.id

        step_row = AgentStep(
            run_id=run_row.id,
            step_key=agent_step_state.step_id,
            step_type=agent_step_state.step_type,
            step_goal=agent_step_state.step_goal,
            status=agent_step_state.status,
            output=agent_step_state.output,
            error=agent_step_state.error,
            tool_trace=agent_step_state.tool_trace,
        )
        await repo.save_step(step_row)
        ids.step_db_id = step_row.id
        await db.commit()
    except Exception as e:
        logger.warning(f"[Agent] 持久化初始化状态失败(非致命): {e}")
        await db.rollback()
    return ids


async def persist_agent_step_result(
    *,
    db,
    ids: AgentPersistenceIds,
    agent_run_state,
    agent_step_state,
) -> None:
    """持久化主 step 完成后的状态:增量更新 AgentStep + AgentRun + 追加 step 历史。

    如果 ids 中对应 db_id 不存在,直接 return。
    失败时 logger.warning + rollback,不抛异常。
    """
    if not ids.run_db_id or not ids.step_db_id:
        return
    try:
        repo = AgentRunRepositoryImpl(db)
        await repo.update_step(
            ids.step_db_id,
            status=agent_step_state.status,
            output=agent_step_state.output,
            error=agent_step_state.error,
            tool_trace=agent_step_state.tool_trace,
        )
        await repo.update_run(
            ids.run_db_id,
            status=agent_run_state.status,
            current_step=agent_run_state.current_step,
            next_step=agent_run_state.next_step,
            completed_steps_summary=agent_run_state.completed_steps_summary,
            artifacts=agent_run_state.artifacts,
            last_error=agent_run_state.last_error or None,
            retry_count=agent_run_state.retry_count,
            budget_remaining=agent_run_state.budget_remaining,
            completed_at=(
                datetime.utcnow()
                if agent_run_state.status in _TERMINAL_STATUSES
                else None
            ),
        )
        # O(1) 追加历史,而非全量重写
        await repo.append_run_step_history(
            ids.run_db_id, _build_step_history_entry(agent_step_state)
        )
        await db.commit()
    except Exception as e:
        logger.warning(f"[Agent] 持久化结束状态失败(非致命): {e}")
        await db.rollback()


async def update_main_step_output(
    *,
    db,
    step_db_id,
    output: str,
) -> None:
    """retry 成功后更新主 step 的 output。

    如果 step_db_id 为空,直接 return。
    失败时 logger.warning + rollback,不抛异常。
    """
    if not step_db_id:
        return
    try:
        repo = AgentRunRepositoryImpl(db)
        await repo.update_step(step_db_id, output=output)
        await db.commit()
    except Exception as e:
        logger.warning(f"[Agent] 更新重试后主输出失败(非致命): {e}")
        await db.rollback()


async def persist_finalize_step(
    *,
    db,
    ids: AgentPersistenceIds,
    agent_run_state,
    finalize_step_state,
) -> AgentPersistenceIds:
    """持久化 finalize step:增量创建 finalize AgentStep + 更新 AgentRun + 追加历史。

    如果 ids.run_db_id 不存在,直接返回 ids。
    失败时 logger.warning + rollback,不抛异常,返回原 ids。
    """
    if not ids.run_db_id:
        return ids
    try:
        repo = AgentRunRepositoryImpl(db)
        if finalize_step_state is not None:
            finalize_row = AgentStep(
                run_id=ids.run_db_id,
                step_key=finalize_step_state.step_id,
                step_type=finalize_step_state.step_type,
                step_goal=finalize_step_state.step_goal,
                status=finalize_step_state.status,
                output=finalize_step_state.output,
                error=finalize_step_state.error,
                tool_trace=finalize_step_state.tool_trace,
            )
            await repo.save_step(finalize_row)
            ids.finalize_step_db_id = finalize_row.id
            await repo.append_run_step_history(
                ids.run_db_id, _build_step_history_entry(finalize_step_state)
            )

        await repo.update_run(
            ids.run_db_id,
            status=agent_run_state.status,
            current_step=agent_run_state.current_step,
            next_step=agent_run_state.next_step,
            completed_steps_summary=agent_run_state.completed_steps_summary,
            artifacts=agent_run_state.artifacts,
            last_error=agent_run_state.last_error or None,
            retry_count=agent_run_state.retry_count,
            budget_remaining=agent_run_state.budget_remaining,
            completed_at=(
                datetime.utcnow()
                if agent_run_state.status in _TERMINAL_STATUSES
                else None
            ),
        )
        await db.commit()
        return ids
    except Exception as e:
        logger.warning(f"[Agent] 持久化finalize步骤失败(非致命): {e}")
        await db.rollback()
        return ids
