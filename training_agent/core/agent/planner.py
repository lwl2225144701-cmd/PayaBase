"""Simple planner that reuses RequestRouter as internal decision capability (应用层门面).

多步计划逻辑下沉到 `core/domain/agent/planner.py`：根据 route 生成真正的
多步计划，步骤数受 max_steps 预算约束。本类保留与编排层的契约
（`build_initial_plan` / `build_followup_step` 签名不变）。
"""

from __future__ import annotations

from dataclasses import asdict

from core.agent.request_router import RequestRouter
from core.agent.state import AgentRunState, AgentStepState
from core.domain.agent.planner import build_initial_steps, decide_followup


class AgentPlanner:
    def __init__(self, router: RequestRouter, max_steps: int = 5):
        self.router = router
        self.max_steps = max_steps

    async def build_initial_plan(
        self,
        *,
        query: str,
        has_attachments: bool,
        has_active_kb: bool,
    ) -> dict:
        route_decision = await self.router.decide(
            query=query,
            has_attachments=has_attachments,
            has_active_kb=has_active_kb,
        )
        steps = build_initial_steps(
            route_decision.route,
            has_attachments=has_attachments,
            has_active_kb=has_active_kb,
            max_steps=self.max_steps,
        )
        return {
            "route_decision": route_decision,
            "steps": [asdict(s) for s in steps],
        }

    @staticmethod
    def build_followup_step(
        run_state: AgentRunState,
        step_state: AgentStepState,
        *,
        max_retries: int,
    ) -> dict | None:
        decision = decide_followup(step_state.status, run_state.retry_count, max_retries)
        # 返回重试步骤时递增 retry_count（与领域决策使用的计数保持先后一致）
        if decision and decision["step_type"] == "retry_decision":
            run_state.retry_count += 1
        return decision
