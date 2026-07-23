"""Agent 多步计划领域服务（Planning Domain Service）。

- 根据 route + 上下文生成**真正多步**的计划（而非单步占位），覆盖
  「先检索 → 分析 → 生成产物」等复杂任务。
- 计划步骤数受 `max_steps`（预算）约束；应用层 `AgentRunner.complete_step`
  每完成一步递减 `budget_remaining`，预算耗尽则停止追加。
- 重试 / 收尾决策集中在 `decide_followup`，供应用层 Planner 调用。

领域层不依赖 `core.agent.*`（应用层运行时状态），只处理纯数据与字符串，
保证可被独立单测。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlanStep:
    step_id: str
    step_type: str
    step_goal: str


# 每种 route 的默认多步模板（步骤类型, 步骤目标）
_STEP_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "rag_qa": [
        ("knowledge_retrieval", "从知识库检索相关上下文"),
        ("answer", "基于检索结果生成回答"),
    ],
    "document_summary": [
        ("knowledge_retrieval", "读取附件 / 文档内容"),
        ("summarize", "生成结构化摘要"),
    ],
    "content_generation": [
        ("knowledge_retrieval", "检索内部资料作为依据"),
        ("draft", "起草正文"),
        ("review", "核验事实与证据后定稿"),
    ],
    "pdf_generation": [
        ("knowledge_retrieval", "检索内部资料作为依据"),
        ("draft", "起草正文"),
        ("pdf_export", "导出 PDF 产物"),
    ],
    "ppt_generation": [
        ("knowledge_retrieval", "检索内部资料作为依据"),
        ("draft", "起草大纲与正文"),
        ("ppt_generation", "生成 PPT 产物"),
    ],
    "fallback_chat": [
        ("respond", "直接回复"),
    ],
}


def build_initial_steps(
    route: str,
    *,
    has_attachments: bool,  # noqa: ARG001 - 预留：未来可按附件调整步骤
    has_active_kb: bool,  # noqa: ARG001 - 预留：未来可按 KB 调整步骤
    max_steps: int = 5,
) -> list[PlanStep]:
    """生成多步计划，步骤数受 max_steps 预算约束。"""
    template = _STEP_TEMPLATES.get(route, [("execute", f"execute_{route}")])
    steps: list[PlanStep] = []
    for i, (step_type, goal) in enumerate(template, start=1):
        steps.append(PlanStep(step_id=f"step-{i}", step_type=step_type, step_goal=goal))
        if len(steps) >= max_steps:
            break
    if not steps:
        steps.append(PlanStep(step_id="step-1", step_type=route, step_goal=f"execute_{route}"))
    return steps


def decide_followup(step_status: str, retry_count: int, max_retries: int) -> dict:
    """失败时由 Planner 决定下一步：重试 or 兜底收尾。

    返回 followup step dict；非失败（成功）返回 finalize 收尾步骤。
    应用层负责在返回 retry 步骤时递增 `retry_count`。
    """
    if step_status == "failed":
        if retry_count < max_retries:
            return {
                "step_id": f"retry-{retry_count + 1}",
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
