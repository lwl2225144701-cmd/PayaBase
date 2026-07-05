"""路由决策和 Agent 初始 step 状态初始化。

只负责:
  - 获取 classify LLM client
  - 创建 RequestRouter + AgentOrchestrator
  - 调用 orchestrator.start_run()
  - 处理 route_decision fallback
  - 生成 first_step + agent_step_state
  - 选择 task_profile
  - 记录 task_profile 到 agent_step_state.tool_trace

不负责:
  - SSE 输出
  - AgentRun / AgentStep 持久化
  - RAG 检索
  - KB miss
  - LLM 正文回答
  - retry / finalize
  - 保存消息
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Any

from core.llm.factory import get_llm_client
from core.agent.request_router import RequestRouter
from core.agent.orchestrator import AgentOrchestrator
from core.agent.strategy import select_task_profile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutingRequest:
    query: str
    has_attachments: bool
    has_active_kb: bool


@dataclass
class RoutingResult:
    orchestrator: Any
    agent_run_state: Any
    agent_step_state: Any
    route_decision: Any
    task_profile: Any
    timings: dict[str, int] = field(default_factory=dict)


async def initialize_chat_routing(
    *,
    request: RoutingRequest,
) -> RoutingResult:
    """路由决策 + Agent 初始状态初始化。

    chat_pipeline.py 负责 persist_initial_agent_run + SSE 输出。
    不捕获异常,由外层统一处理。
    """
    t0 = time.time()

    router_llm = get_llm_client("classify")
    router = RequestRouter(router_llm)
    orchestrator = AgentOrchestrator(router)
    agent_run_state, agent_plan = await orchestrator.start_run(
        query=request.query,
        has_attachments=request.has_attachments,
        has_active_kb=request.has_active_kb,
    )

    route_decision = agent_run_state.route_decision
    if route_decision is None:
        route_decision = await router.decide(
            query=request.query,
            has_attachments=request.has_attachments,
            has_active_kb=request.has_active_kb,
        )
        agent_run_state.route_decision = route_decision
        agent_run_state.plan_snapshot = {
            "steps": [
                {
                    "step_id": "step-1",
                    "step_type": route_decision.route,
                    "step_goal": f"execute_{route_decision.route}",
                }
            ],
            "route": route_decision.route,
        }

    first_step = (
        agent_plan["steps"][0]
        if agent_plan.get("steps")
        else {
            "step_id": "step-1",
            "step_type": route_decision.route,
            "step_goal": f"execute_{route_decision.route}",
        }
    )

    agent_step_state = orchestrator.runner.start_step(agent_run_state, first_step)

    task_profile = select_task_profile(
        route=route_decision.route,
        query=request.query,
    )
    agent_step_state.tool_trace.append(
        {
            "type": "task_profile",
            "goal_type": task_profile.goal_type,
            "content_type": task_profile.content_type,
            "evidence_policy": task_profile.evidence_policy,
            "artifact_required": task_profile.artifact_required,
            "artifact_tool": task_profile.artifact_tool,
            "completion_condition": task_profile.completion_condition,
        }
    )

    return RoutingResult(
        orchestrator=orchestrator,
        agent_run_state=agent_run_state,
        agent_step_state=agent_step_state,
        route_decision=route_decision,
        task_profile=task_profile,
        timings={"routing_ms": int((time.time() - t0) * 1000)},
    )
