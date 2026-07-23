"""Task-profile 选择领域服务（Task Profile Domain Service）。

为自主 Agent 执行选择任务画像（目标类型 / 证据策略 / 完成条件 / 约束）。
纯逻辑，不依赖 LLM 或 IO。

修复：原 `core/agent/strategy.py` 中两段完全相同的
`if evidence_policy == "internal_first_external_supplement":` 已合并为单一分支。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaskProfile:
    goal_type: str
    route: str
    content_type: str
    evidence_policy: str
    search_focus_rule: str = "none"
    artifact_required: bool = False
    artifact_tool: str | None = None
    allow_external_search: bool = False
    completion_condition: str = "final_answer_ready"
    constraints: list[str] = field(default_factory=list)

    def build_instruction(self) -> str:
        lines = [
            f"当前任务目标类型: {self.goal_type}",
            f"当前内容类型: {self.content_type}",
            f"当前资料策略: {self.evidence_policy}",
            f"完成条件: {self.completion_condition}",
        ]
        if self.search_focus_rule != "none":
            lines.append(f"外部搜索目标规则: {self.search_focus_rule}")
        if self.constraints:
            lines.append("执行约束:")
            lines.extend(f"- {item}" for item in self.constraints)
        return "\n".join(lines)


def select_task_profile(*, route: str, query: str) -> TaskProfile:
    text = (query or "").strip()
    content_type = _infer_content_type(text)
    evidence_policy = _infer_evidence_policy(text)
    artifact_tool = _route_to_artifact_tool(route)
    artifact_required = artifact_tool is not None
    allow_external_search = evidence_policy != "internal_only" and route in {
        "content_generation",
        "pdf_generation",
        "ppt_generation",
    }

    constraints = [
        "优先复用内部资料和知识库证据，不要编造事实。",
        "只有内部资料不足且问题确实依赖外部公开信息时，才允许调用 web_search。",
    ]

    search_focus_rule = "none"
    # 合并后的单一分支：internal_first_external_supplement 同时设置搜索焦点与补充约束
    if evidence_policy == "internal_first_external_supplement":
        search_focus_rule = "focus_entities_in_materials"
        constraints.append(
            "当 knowledge_retrieval 返回未找到相关信息、资料有限或证据不足时，"
            "应继续尝试 web_search，而不是直接结束。"
        )

    if artifact_required:
        constraints.append(f"当正文已经可导出时，必须继续调用 {artifact_tool} 生成最终产物。")
    else:
        constraints.append("当前任务不要求生成产物，完成高质量正文后即可结束。")

    return TaskProfile(
        goal_type=_infer_goal_type(route, artifact_tool),
        route=route,
        content_type=content_type,
        evidence_policy=evidence_policy,
        search_focus_rule=search_focus_rule,
        artifact_required=artifact_required,
        artifact_tool=artifact_tool,
        allow_external_search=allow_external_search,
        completion_condition=_infer_completion_condition(artifact_tool),
        constraints=constraints,
    )


def _infer_goal_type(route: str, artifact_tool: str | None) -> str:
    if artifact_tool == "pdf_export":
        return "artifact_pdf"
    if artifact_tool == "ppt_generation":
        return "artifact_ppt"
    if route == "document_summary":
        return "structured_summary"
    if route == "content_generation":
        return "structured_generation"
    return "answer"


def _infer_completion_condition(artifact_tool: str | None) -> str:
    if artifact_tool == "pdf_export":
        return "pdf_task_created"
    if artifact_tool == "ppt_generation":
        return "ppt_task_created"
    return "final_answer_ready"


def _route_to_artifact_tool(route: str) -> str | None:
    if route == "pdf_generation":
        return "pdf_export"
    if route == "ppt_generation":
        return "ppt_generation"
    return None


def _infer_content_type(text: str) -> str:
    if _contains_any(
        text,
        (
            "工作经历", "简历", "履历", "任职经历", "职业经历",
            "人物经历", "工作背景",
        ),
    ):
        return "person_experience_summary"
    if _contains_any(text, ("培训方案", "培训计划", "培训大纲", "培训课程")):
        return "training_plan"
    if _contains_any(text, ("调研", "分析报告", "方案", "总结")):
        return "analysis_report"
    return "general_content"


def _infer_evidence_policy(text: str) -> str:
    if _contains_any(text, ("允许联网", "联网搜索", "外部搜索", "公开信息", "网上搜索")):
        return "internal_first_external_supplement"
    return "internal_only"


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)
