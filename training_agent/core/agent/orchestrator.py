"""Top-level orchestrator for autonomous agent runs."""

from __future__ import annotations

from core.agent.planner import AgentPlanner
from core.agent.policy import AgentPolicy
from core.agent.request_router import RequestRouter
from core.agent.runner import AgentRunner
from core.agent.state import AgentRunState


class AgentOrchestrator:
    def __init__(self, router: RequestRouter, policy: AgentPolicy | None = None):
        self.router = router
        self.policy = policy or AgentPolicy()
        self.planner = AgentPlanner(router, max_steps=self.policy.max_steps)
        self.runner = AgentRunner()

    async def start_run(
        self,
        *,
        query: str,
        has_attachments: bool,
        has_active_kb: bool,
    ) -> tuple[AgentRunState, dict]:
        run_state = AgentRunState.create(goal=query, budget_remaining=self.policy.max_steps)
        plan = await self.planner.build_initial_plan(
            query=query,
            has_attachments=has_attachments,
            has_active_kb=has_active_kb,
        )
        route = plan["route_decision"].route
        if not self.policy.route_allowed(route):
            run_state.status = "failed"
            run_state.last_error = f"route_not_allowed:{route}"
            return run_state, plan
        run_state.route_decision = plan["route_decision"]
        run_state.plan_snapshot = {"steps": plan["steps"], "route": route}
        if plan["steps"]:
            run_state.current_step = plan["steps"][0]["step_id"]
        return run_state, plan
