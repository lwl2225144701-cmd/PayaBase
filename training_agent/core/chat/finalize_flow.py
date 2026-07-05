"""Finalize / retry 流程:Agent follow-up step 执行。

只负责:
  - 构造 followup_step_def
  - 创建 finalize_step_state
  - retry_decision + retry_backoff + LLM 重调
  - fallback_finalize
  - complete finalize step
  - 返回 content_suffix / finalize_step_state / finalize_trace

不负责:
  - SSE 输出
  - AgentRun / AgentStep 持久化
  - RAG 检索
  - 普通 LLM 回答
  - Artifact 生成
  - 保存 assistant message
"""

import asyncio
import logging
from dataclasses import dataclass, field

from core.prompts.agent import build_step_execution_prompt
from core.prompts.router import FALLBACK_CHAT_SYSTEM_PROMPT
from core.chat.stream_events import stream_llm_response

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FinalizeFlowRequest:
    user_message_text: str
    history_messages: list[dict]
    available_tools: list[str]
    artifacts: list[dict]


@dataclass
class FinalizeFlowState:
    content_suffix: str = ""
    finalize_step_state: object | None = None
    finalize_trace: list[dict] = field(default_factory=list)
    timings: dict[str, int] = field(default_factory=dict)
    error: str | None = None


async def stream_finalize_flow(
    *,
    llm,
    orchestrator,
    agent_run_state,
    agent_step_state,
    request: FinalizeFlowRequest,
    state: FinalizeFlowState,
):
    """流式执行 Agent follow-up / retry / finalize,yield 纯文本 chunk。

    chat_pipeline.py 负责 SSE 包装和 persist_finalize_step 持久化。
    """
    followup_step_def = orchestrator.planner.build_followup_step(
        agent_run_state,
        agent_step_state,
        max_retries=orchestrator.policy.max_retries,
    )
    if not followup_step_def:
        return

    # 追加到 plan_snapshot
    snapshot_steps = (agent_run_state.plan_snapshot or {}).get("steps", [])
    snapshot_steps.append(followup_step_def)
    agent_run_state.plan_snapshot["steps"] = snapshot_steps

    finalize_step_state = orchestrator.runner.start_step(agent_run_state, followup_step_def)
    state.finalize_step_state = finalize_step_state

    finalize_output = "agent_finalize_completed"
    finalize_already_completed = False
    finalize_trace: list[dict] = [
        {
            "type": "followup",
            "step_type": followup_step_def.get("step_type"),
            "step_goal": followup_step_def.get("step_goal"),
        }
    ]

    # retry_decision
    if followup_step_def.get("step_type") == "retry_decision":
        retry_output = ""
        retry_error = ""
        remaining_attempts = max(
            1, orchestrator.policy.max_retries - agent_run_state.retry_count + 1
        )
        for attempt in range(1, remaining_attempts + 1):
            if retry_error and not orchestrator.policy.is_retryable_error(retry_error):
                break
            retry_error = ""
            try:
                retry_system_prompt = build_step_execution_prompt(
                    base_system_prompt=FALLBACK_CHAT_SYSTEM_PROMPT,
                    goal=agent_run_state.goal,
                    plan_snapshot=agent_run_state.plan_snapshot,
                    current_step=followup_step_def.get("step_id") or "retry-1",
                    next_step=None,
                    completed_steps_summary=agent_run_state.completed_steps_summary,
                    available_tools=request.available_tools,
                )
                retry_messages = [{"role": "system", "content": retry_system_prompt}]
                for msg in request.history_messages:
                    retry_messages.append({"role": msg["role"], "content": msg["content"]})
                retry_messages.append({"role": "user", "content": request.user_message_text})
                async for chunk in stream_llm_response(llm, retry_messages, temperature=0.1):
                    if chunk:
                        retry_output += chunk
                        yield chunk
                if retry_output:
                    break
                retry_error = "retry_empty_output"
            except Exception as retry_exc:
                retry_error = str(retry_exc)
            if (
                retry_error
                and attempt < remaining_attempts
                and orchestrator.policy.is_retryable_error(retry_error)
            ):
                delay = orchestrator.policy.retry_backoff_seconds(attempt)
                finalize_trace.append(
                    {
                        "type": "retry_backoff",
                        "attempt": attempt,
                        "delay_sec": round(delay, 3),
                        "error": retry_error[:200],
                    }
                )
                await asyncio.sleep(delay)

        if retry_output:
            state.content_suffix = f"\n\n[重试结果]\n{retry_output}"
            finalize_output = "retry_reexecute_success"
        else:
            finalize_output = "retry_reexecute_failed"
            if not retry_error:
                retry_error = "retry_empty_output"

        finalize_trace.append(
            {
                "type": "retry",
                "retry_count": agent_run_state.retry_count,
                "max_retries": orchestrator.policy.max_retries,
                "decision": "retry_reexecute_once",
                "retry_error": retry_error[:1000] if retry_error else "",
            }
        )

        if retry_error:
            retry_error_type = orchestrator.policy.classify_error(retry_error)
            fallback_on_retry = orchestrator.policy.fallback_message_for(retry_error_type)
            state.content_suffix = f"{state.content_suffix}\n\n{fallback_on_retry}"
            orchestrator.runner.complete_step(
                agent_run_state,
                finalize_step_state,
                output=finalize_output,
                tool_trace=finalize_trace
                + [{"type": "artifacts", "items": request.artifacts}],
                error=f"{retry_error_type}:{retry_error}",
            )
            agent_run_state.last_error = f"{retry_error_type}:{retry_error[:1000]}"
            finalize_already_completed = True
        else:
            orchestrator.runner.complete_step(
                agent_run_state,
                finalize_step_state,
                output=finalize_output,
                tool_trace=finalize_trace
                + [{"type": "artifacts", "items": request.artifacts}],
            )
            finalize_already_completed = True

    # fallback_finalize
    if followup_step_def.get("step_type") == "fallback_finalize":
        finalize_output = "fallback_finalize_completed"
        finalize_trace.append(
            {"type": "fallback", "message": "reroute_to_safe_fallback_response"}
        )

    # complete step (if not done by retry error branch)
    if finalize_step_state is not None and not finalize_already_completed:
        orchestrator.runner.complete_step(
            agent_run_state,
            finalize_step_state,
            output=finalize_output,
            tool_trace=finalize_trace
            + [{"type": "artifacts", "items": request.artifacts}],
        )

    state.finalize_trace = finalize_trace
    state.error = retry_error if followup_step_def.get("step_type") == "retry_decision" and retry_error else None
