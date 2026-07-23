"""Runner utilities for step lifecycle transitions (应用层).

状态语义统一使用领域层 `AgentRunStatus` 常量（禁止硬编码 "failed"/"running"）。

设计要点（与单步执行编排兼容）：
- 当前编排对一次请求执行「单个主步骤 + finalize 收尾」。多步计划用于预算与
  未来多步执行，主步骤完成后进入 finalize 落终态，因此主步骤 complete 后
  一律保持 RUNNING，把终止/重试决策交给 finalize_flow（也即 Planner）。
- 主步骤出错时**保留 RUNNING**（修复 #2：原 Runner 直接写 FAILED+done 与
  Planner 的重试逻辑自相矛盾），由 Planner 的 `build_followup_step` 决定重试。
- 每完成一步递减 `budget_remaining`（修复 #1：原 max_steps 预算从未被消费）。
- finalize/retry/fallback 步骤沿用原终止逻辑（改用领域状态常量）。
"""

from __future__ import annotations

from core.agent.state import AgentRunState, AgentStepState
from core.domain.agent.aggregates import AgentRunStatus


class AgentRunner:
    @staticmethod
    def _locate_next_step(run_state: AgentRunState) -> dict | None:
        steps = (run_state.plan_snapshot or {}).get("steps", [])
        if not steps:
            return None
        current = run_state.current_step
        if not current:
            return steps[0]
        for idx, step in enumerate(steps):
            if step.get("step_id") == current:
                if idx + 1 < len(steps):
                    return steps[idx + 1]
                return None
        return None

    def start_step(self, run_state: AgentRunState, step: dict) -> AgentStepState:
        run_state.current_step = step["step_id"]
        next_step = self._locate_next_step(run_state)
        run_state.next_step = next_step["step_id"] if next_step else None
        return AgentStepState(
            step_id=step["step_id"],
            step_type=step["step_type"],
            step_goal=step["step_goal"],
            status="running",
        )

    def complete_step(
        self,
        run_state: AgentRunState,
        step_state: AgentStepState,
        *,
        output: str,
        artifacts: list[dict] | None = None,
        tool_trace: list[dict] | None = None,
        error: str = "",
    ) -> AgentRunState:
        step_state.output = output or ""
        step_state.error = error
        if tool_trace:
            step_state.tool_trace = tool_trace
        step_state.status = "failed" if error else "success"

        # 预算递减（修复 #1：max_steps 真正被消费）
        run_state.budget_remaining = max(0, run_state.budget_remaining - 1)

        run_state.add_step_result(step_state)
        if artifacts:
            run_state.artifacts.extend(artifacts)
        run_state.last_error = error or run_state.last_error

        plan_steps = (run_state.plan_snapshot or {}).get("steps", [])
        is_plan_step = any(s.get("step_id") == step_state.step_id for s in plan_steps)

        # 主（plan）步骤：完成后进入 finalize 收尾，终态由 finalize 落定。
        # 出错时保留 RUNNING，把重试决策权交给 Planner（修复 #2）。
        if is_plan_step:
            run_state.status = AgentRunStatus.RUNNING
            run_state.next_step = None
            return run_state

        # finalize / retry / fallback 步骤：沿用原终止逻辑（仅改用领域状态常量）
        if error:
            run_state.status = AgentRunStatus.FAILED
            run_state.next_step = "done"
            return run_state
        next_step = self._locate_next_step(run_state)
        if next_step:
            run_state.status = AgentRunStatus.RUNNING
            run_state.next_step = next_step["step_id"]
        else:
            run_state.status = AgentRunStatus.COMPLETED
            run_state.next_step = "done"
        return run_state
