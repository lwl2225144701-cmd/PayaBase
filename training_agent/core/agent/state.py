"""Agent state models for orchestrated multi-step execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

from core.agent.request_router import RouteDecision


@dataclass
class AgentStepState:
    step_id: str
    step_type: str
    step_goal: str
    status: str = "pending"  # pending|running|success|failed
    output: str = ""
    error: str = ""
    tool_trace: list[dict] = field(default_factory=list)


@dataclass
class AgentRunState:
    run_id: str
    goal: str
    status: str = "running"  # running|completed|failed|stopped
    route_decision: Optional[RouteDecision] = None
    current_step: Optional[str] = None
    next_step: Optional[str] = None
    completed_steps: list[str] = field(default_factory=list)
    completed_steps_summary: str = ""
    step_history: list[dict] = field(default_factory=list)
    artifacts: list[dict] = field(default_factory=list)
    retry_count: int = 0
    budget_remaining: int = 0
    last_error: str = ""
    plan_snapshot: dict = field(default_factory=dict)

    @staticmethod
    def create(goal: str, budget_remaining: int) -> "AgentRunState":
        return AgentRunState(
            run_id=str(uuid4()),
            goal=goal,
            budget_remaining=budget_remaining,
        )

    def add_step_result(self, step: AgentStepState) -> None:
        self.step_history.append(
            {
                "step_id": step.step_id,
                "step_type": step.step_type,
                "step_goal": step.step_goal,
                "status": step.status,
                "output": step.output[:500],
                "error": step.error[:500],
                "tool_trace": step.tool_trace[-10:] if step.tool_trace else [],
            }
        )
        if step.status == "success":
            self.completed_steps.append(step.step_id)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        if not self.step_history:
            self.completed_steps_summary = ""
            return
        self.completed_steps_summary = " | ".join(
            f"{item['step_id']}:{item['status']}"
            for item in self.step_history[-5:]
        )
