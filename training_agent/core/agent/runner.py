"""Runner utilities for step lifecycle transitions."""

from __future__ import annotations

from core.agent.state import AgentRunState, AgentStepState


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
        run_state.add_step_result(step_state)
        if artifacts:
            run_state.artifacts.extend(artifacts)
        if error:
            run_state.status = "failed"
            run_state.next_step = "done"
            return run_state
        next_step = self._locate_next_step(run_state)
        if next_step:
            run_state.status = "running"
            run_state.next_step = next_step["step_id"]
        else:
            run_state.status = "completed"
            run_state.next_step = "done"
        return run_state
