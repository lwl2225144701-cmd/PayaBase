"""普通 LLM 回答流程:document_summary / content_generation / rag_qa / fallback。

只负责:
  - 根据 route 构造 system_prompt
  - 构造 step_prompt
  - 调用 stream_llm_response
  - 产出纯文本 chunk / timings

不负责:
  - SSE 输出
  - Agent 执行 / 持久化
  - RAG 检索
  - PPT/PDF Artifact
  - KB miss / 联网搜索
  - 保存消息
"""

import logging
import time
from dataclasses import dataclass, field

from core.prompts.chat import (
    build_attachment_only_prompt,
    build_attachment_with_kb_prompt,
    build_kb_only_prompt,
    FALLBACK_PROMPT,
)
from core.prompts.router import (
    build_content_generation_prompt,
    build_document_summary_prompt,
    FALLBACK_CHAT_SYSTEM_PROMPT,
)
from core.prompts.agent import build_step_execution_prompt
from core.chat.stream_events import stream_llm_response
from core.chat.chat_context import build_context_from_chunks

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnswerStepContext:
    """构造 step_prompt 的参数包,不传 agent_run_state 整个对象。"""
    goal: str
    plan_snapshot: dict
    current_step: str | None
    next_step: str | None
    completed_steps_summary: str
    available_tools: list[str]


@dataclass(frozen=True)
class AnswerGenerationRequest:
    """普通 LLM 回答输入参数包。"""
    route: str
    user_message_text: str
    material_text: str
    source_hint: str
    chunks_data: list[dict]
    has_attachments: bool
    history_messages: list[dict]
    step_context: AnswerStepContext


@dataclass
class AnswerStreamState:
    """流式回答的状态容器。"""
    timings: dict[str, int] = field(default_factory=dict)
    content: str = ""


async def stream_answer_chunks(
    *,
    llm,
    request: AnswerGenerationRequest,
    state: AnswerStreamState,
):
    """流式产出纯文本 chunk,yield 纯文本,不 yield SSE。

    chat_pipeline.py 负责 SSE 包装和 ask-pending 逻辑。
    """
    route = request.route

    # 1. 根据 route 构造 system_prompt
    if route == "document_summary":
        system_prompt = build_document_summary_prompt(
            request.material_text or request.user_message_text, request.source_hint
        )
    elif route == "content_generation":
        system_prompt = build_content_generation_prompt(
            request.material_text or request.user_message_text, request.source_hint
        )
    elif route == "rag_qa":
        if request.has_attachments and request.chunks_data:
            system_prompt = build_attachment_with_kb_prompt(
                build_context_from_chunks(request.chunks_data), source_type="local"
            )
        elif request.has_attachments:
            system_prompt = build_attachment_only_prompt(source_type="local")
        elif request.chunks_data:
            system_prompt = build_kb_only_prompt(
                build_context_from_chunks(request.chunks_data)
            )
        else:
            system_prompt = FALLBACK_PROMPT
    else:
        system_prompt = FALLBACK_CHAT_SYSTEM_PROMPT

    # 2. 构造 step_prompt
    sc = request.step_context
    step_prompt = build_step_execution_prompt(
        base_system_prompt=system_prompt,
        goal=sc.goal,
        plan_snapshot=sc.plan_snapshot,
        current_step=sc.current_step or "step-1",
        next_step=sc.next_step,
        completed_steps_summary=sc.completed_steps_summary,
        available_tools=sc.available_tools,
    )

    # 3. 拼接 history
    messages: list[dict] = [{"role": "system", "content": step_prompt}]
    for msg in request.history_messages:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": request.user_message_text})

    # 4. 流式调用 LLM
    logger.info(
        f"[Timing] 调用LLM开始, route={route}, "
        f"model={llm.model}, messages={len(messages)}"
    )
    t0 = time.time()
    async for chunk in stream_llm_response(llm, messages, temperature=0.1):
        if chunk:
            if "llm_first_token_ms" not in state.timings:
                state.timings["llm_first_token_ms"] = int((time.time() - t0) * 1000)
                logger.info(
                    f"[Timing] LLM首token: {state.timings['llm_first_token_ms']}ms"
                )
            state.content += chunk
            yield chunk

    state.timings["llm_total_ms"] = int((time.time() - t0) * 1000)
    logger.info(
        f"[Timing] LLM响应完成: {state.timings['llm_total_ms']}ms, "
        f"chars={len(state.content)}"
    )
