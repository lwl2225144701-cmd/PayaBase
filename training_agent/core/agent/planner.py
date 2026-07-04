"""Simple planner that reuses RequestRouter as internal decision capability."""

from __future__ import annotations

from core.agent.request_router import RequestRouter
from core.agent.state import AgentRunState, AgentStepState


class AgentPlanner:
    def __init__(self, router: RequestRouter):
        self.router = router

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
        steps = self._build_steps(route_decision.route)
        return {
            "route_decision": route_decision,
            "steps": steps,
        }

    @staticmethod
    def _build_steps(route: str) -> list[dict]:
        return [
            {
                "step_id": "step-1",
                "step_type": route,
                "step_goal": f"execute_{route}",
            },
        ]

    @staticmethod
    def build_followup_step(
        run_state: AgentRunState,
        step_state: AgentStepState,
        *,
        max_retries: int,
    ) -> dict | None:
        if step_state.status == "failed":
            if run_state.retry_count < max_retries:
                run_state.retry_count += 1
                return {
                    "step_id": f"retry-{run_state.retry_count}",
                    "step_type": "retry_decision",
                    "step_goal": "decide_retry_or_fallback",
                }
            return {
                "step_id": "fallback-1",
                "step_type": "fallback_finalize",
                "step_goal": "fallback_and_finalize_response",
            }
        return {
            "step_id": "finalize-1",
            "step_type": "finalize_response",
            "step_goal": "finalize_and_record_agent_result",
        }
