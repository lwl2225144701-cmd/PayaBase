"""对话最终收尾流程。

只负责:
  - 计算总耗时
  - 写 timings["total_ms"]
  - 组装 assistant message context
  - 调用 save_assistant_message
  - 构造 agent / finished payload

不负责:
  - SSE 输出
  - RAG 检索
  - LLM 回答
  - Artifact 生成
  - autonomous agent 执行
  - retry / finalize
"""

import time
from dataclasses import dataclass, field
from typing import Any

from core.chat.conversation_service import save_assistant_message


@dataclass(frozen=True)
class CompletionRequest:
    conversation_id: Any
    content: str
    citations: list[dict]
    route: str
    decision_source: str
    reason: str
    confidence: float
    agent_run_id: str
    agent_run_db_id: str | None
    agent_status: str
    agent_current_step: str | None
    agent_next_step: str | None
    completed_steps_summary: str
    artifacts: list[dict]
    timings: dict
    attachment_used: bool
    web_search_mode: str
    started_at: float


@dataclass
class CompletionResult:
    latency_ms: int
    agent_payload: dict
    finished_payload: dict


async def complete_chat_response(
    *,
    db,
    request: CompletionRequest,
) -> CompletionResult:
    """收尾:保存消息 + 构造最终 SSE payload。

    chat_pipeline.py 负责 SSE 输出,本函数只返回结果。
    """
    latency_ms = int((time.time() - request.started_at) * 1000)
    request.timings["total_ms"] = latency_ms

    context = {
        "route": request.route,
        "decision_source": request.decision_source,
        "reason": request.reason,
        "confidence": request.confidence,
        "agent": {
            "run_id": request.agent_run_id,
            "run_db_id": request.agent_run_db_id,
            "status": request.agent_status,
            "current_step": request.agent_current_step,
            "next_step": request.agent_next_step,
            "completed_steps_summary": request.completed_steps_summary,
        },
        "artifacts": request.artifacts,
        "timings": request.timings,
    }

    await save_assistant_message(
        conversation_id=request.conversation_id,
        content=request.content,
        citations=request.citations,
        context=context,
        token_count=len(request.content.split()),
        latency_ms=latency_ms,
        db=db,
    )

    agent_payload = {
        "run_id": request.agent_run_id,
        "run_db_id": request.agent_run_db_id,
        "status": request.agent_status,
        "current_step": request.agent_current_step,
        "next_step": request.agent_next_step,
        "completed_steps_summary": request.completed_steps_summary,
    }

    finished_payload = {
        "web_search_mode": request.web_search_mode,
    }

    return CompletionResult(
        latency_ms=latency_ms,
        agent_payload=agent_payload,
        finished_payload=finished_payload,
    )
