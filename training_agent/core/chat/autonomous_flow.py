"""Autonomous agent 工具执行流程。

只负责:
  - 构造 ToolRegistry + 注册工具
  - 构造 autonomous_system_prompt
  - 创建 AgentStepExecutor
  - 调用 executor.run()
  - 产出纯文本 chunk
  - 收集 artifacts / tool_trace
  - artifact_required 补偿逻辑

不负责:
  - SSE 输出
  - AgentRun / AgentStep 持久化
  - RAG 检索
  - 普通 LLM 回答
  - PPT/PDF 直接 route 生成
  - retry / finalize
  - 保存消息
  - KB miss / 联网搜索状态写回
"""

import json
import logging
import time
from dataclasses import dataclass, field

from core.config import settings
from core.agent.executor import AgentStepExecutor
from core.tools.registry import ToolRegistry
from core.tools.knowledge_tool import KnowledgeRetrievalTool
from core.tools.solution_tool import SolutionGeneratorTool
from core.tools.web_search_tool import WebSearchTool
from core.tools.ppt_tool import PPTGenerationTool
from core.tools.pdf_export_tool import PDFExportTool
from core.prompts.agent import SOLUTION_AGENT_PROMPT

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AutonomousExecutionRequest:
    """Autonomous agent 执行输入参数包。"""
    query: str
    history_messages: list[dict]
    tenant_id: str
    conversation_title: str
    active_kb_id: str | None
    active_kb_name: str
    web_search_enabled: bool
    task_profile: object


@dataclass
class AutonomousExecutionState:
    """Autonomous agent 执行过程输出容器。"""
    content: str = ""
    artifacts: list[dict] = field(default_factory=list)
    tool_trace: list[dict] = field(default_factory=list)
    timings: dict[str, int] = field(default_factory=dict)


async def stream_autonomous_execution(
    *,
    llm,
    request: AutonomousExecutionRequest,
    state: AutonomousExecutionState,
):
    """流式执行 autonomous agent tools,yield 纯文本 chunk。

    chat_pipeline.py 负责 SSE 包装和 yield。
    异常不捕获,由外层 try 统一处理。
    """
    tp = request.task_profile

    # 1. 构造 ToolRegistry
    registry = ToolRegistry()
    if request.active_kb_id:
        registry.register(
            KnowledgeRetrievalTool(
                kb_id=request.active_kb_id,
                kb_name=request.active_kb_name,
            )
        )
    if request.web_search_enabled:
        registry.register(WebSearchTool())
    registry.register(SolutionGeneratorTool(llm))
    registry.register(PPTGenerationTool(tenant_id=request.tenant_id))
    registry.register(PDFExportTool(tenant_id=request.tenant_id))

    # 2. 构造 system prompt
    if request.web_search_enabled:
        autonomous_system_prompt = (
            f"{SOLUTION_AGENT_PROMPT}\n\n"
            f"当前状态：web_search 工具已就绪。"
        )
    else:
        autonomous_system_prompt = (
            "你是一个个人 AI 知识库助手自治执行器。\n"
            f"{tp.build_instruction()}\n"
            "必须严格围绕当前目标选择工具。"
        )

    # 3. 创建 executor
    executor = AgentStepExecutor(
        llm_client=llm,
        registry=registry,
        system_prompt=autonomous_system_prompt,
        max_iterations=settings.max_iterations,
    )

    # 4. 流式执行
    t0 = time.time()
    logger.info(
        f"[Timing] 自治Agent工具链开始, tools={registry.list_tools()}"
    )
    async for chunk in executor.run(
        query=request.query,
        history=request.history_messages,
    ):
        if chunk:
            if "llm_first_token_ms" not in state.timings:
                state.timings["llm_first_token_ms"] = int((time.time() - t0) * 1000)
            state.content += chunk
            yield chunk

    state.timings["llm_total_ms"] = int((time.time() - t0) * 1000)
    state.artifacts.extend(executor.artifacts)
    state.tool_trace.extend(executor.tool_trace)

    # 5. artifact_required 补偿逻辑
    if (
        tp.artifact_required
        and not state.artifacts
        and state.content
        and "请提供" not in state.content
        and "资料不足" not in state.content
        and "生成回答时出现错误" not in state.content
    ):
        registry_tool = registry.get(tp.artifact_tool or "")
        if registry_tool:
            artifact_result_raw = registry_tool.invoke(
                content=state.content,
                title=request.conversation_title or "知识整理",
            )
            state.tool_trace.append(
                {
                    "type": "task_profile_enforced_tool",
                    "tool_name": tp.artifact_tool,
                    "goal_type": tp.goal_type,
                    "content_type": tp.content_type,
                    "result_preview": artifact_result_raw[:500],
                }
            )
            try:
                artifact_result = json.loads(artifact_result_raw)
            except json.JSONDecodeError:
                artifact_result = {}
            task_id = artifact_result.get("task_id")
            if task_id:
                artifact_type = "pdf" if tp.artifact_tool == "pdf_export" else "ppt"
                state.artifacts.append({"type": artifact_type, "task_id": task_id})
