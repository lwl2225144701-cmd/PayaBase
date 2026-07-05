"""Artifact 生成流程:PPT/PDF 直接生成。

只负责:
  - 根据 route 构造 PPT/PDF prompt
  - 构造 step_prompt
  - 调用 stream_llm_response 生成正文
  - 调用 PPTGenerationTool / PDFExportTool
  - 解析 task_id
  - 返回结果对象

不负责:
  - SSE 输出
  - Agent 执行
  - Agent 持久化
  - RAG 检索
  - KB miss / 联网搜索
"""

import json
import logging
import time
from dataclasses import dataclass, field

from core.tools.ppt_tool import PPTGenerationTool
from core.tools.pdf_export_tool import PDFExportTool
from core.prompts.router import build_ppt_generation_prompt, build_pdf_generation_prompt
from core.prompts.agent import build_step_execution_prompt
from core.chat.stream_events import stream_llm_response

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArtifactStepContext:
    """构造 step_prompt 的参数包,不传 agent_run_state 整个对象。"""
    goal: str
    plan_snapshot: dict
    current_step: str | None
    next_step: str | None
    completed_steps_summary: str
    available_tools: list[str]


@dataclass(frozen=True)
class ArtifactGenerationRequest:
    """PPT/PDF 生成输入参数包。"""
    route: str
    material_text: str
    message: str
    source_hint: str
    conversation_title: str
    tenant_id: str
    history_messages: list[dict]
    step_context: ArtifactStepContext


@dataclass
class ArtifactGenerationResult:
    """PPT/PDF 生成输出结果包。"""
    content: str = ""
    artifacts: list[dict] = field(default_factory=list)
    timings: dict[str, int] = field(default_factory=dict)


async def generate_route_artifact(
    *,
    llm,
    request: ArtifactGenerationRequest,
) -> ArtifactGenerationResult:
    """执行 PPT/PDF 直接生成流程,返回结果对象。

    chat_pipeline.py 负责 SSE 输出,本函数不 yield SSE。
    异常不捕获,由外层 try 统一处理。
    """
    route = request.route

    if route == "ppt_generation":
        prompt = build_ppt_generation_prompt(
            request.material_text or request.message, request.source_hint
        )
        tool = PPTGenerationTool(tenant_id=request.tenant_id)
        artifact_type = "ppt"
    elif route == "pdf_generation":
        prompt = build_pdf_generation_prompt(
            request.material_text or request.message, request.source_hint
        )
        tool = PDFExportTool(tenant_id=request.tenant_id)
        artifact_type = "pdf"
    else:
        raise ValueError(f"unsupported artifact route: {route!r}")

    sc = request.step_context
    step_prompt = build_step_execution_prompt(
        base_system_prompt=prompt,
        goal=sc.goal,
        plan_snapshot=sc.plan_snapshot,
        current_step=sc.current_step or "step-1",
        next_step=sc.next_step,
        completed_steps_summary=sc.completed_steps_summary,
        available_tools=sc.available_tools,
    )

    messages: list[dict] = [{"role": "system", "content": step_prompt}]
    for msg in request.history_messages:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": request.message})

    t0 = time.time()
    timings: dict[str, int] = {}
    logger.info(
        f"[Timing] {route} 链路调用LLM开始, "
        f"model={llm.model}, messages={len(messages)}"
    )
    full_content = ""
    async for chunk in stream_llm_response(llm, messages, temperature=0.2):
        if "llm_first_token_ms" not in timings:
            timings["llm_first_token_ms"] = int((time.time() - t0) * 1000)
        full_content += chunk
    timings["llm_total_ms"] = int((time.time() - t0) * 1000)
    logger.info(
        f"[Timing] {route} 链路LLM完成: "
        f"{timings['llm_total_ms']}ms, chars={len(full_content)}"
    )

    task_payload = json.loads(
        tool.invoke(content=full_content, title=request.conversation_title or "知识整理")
    )
    artifacts: list[dict] = []
    if task_payload.get("task_id"):
        artifacts.append({"type": artifact_type, "task_id": task_payload["task_id"]})

    summary_text = task_payload.get("message") or (
        f"{'PPT' if route == 'ppt_generation' else 'PDF'} 生成任务已提交。"
    )
    if request.source_hint:
        summary_text += f"\n来源：{request.source_hint}"

    return ArtifactGenerationResult(
        content=summary_text,
        artifacts=artifacts,
        timings=timings,
    )
