"""Agent 领域服务单测（DDD 重构后）。

覆盖 #1 多步计划 + 预算、#2 Runner 失败语义、#3 路由否定词/置信度、
#5 错误分类一致性、#6 strategy 重复 if 合并。#4/#7 由集成/代码审查覆盖。
"""

import pytest

from core.agent.planner import AgentPlanner
from core.agent.runner import AgentRunner
from core.agent.state import AgentRunState, AgentStepState
from core.domain.agent.planner import PlanStep, build_initial_steps, decide_followup
from core.domain.agent.policy import classify_error, is_retryable_error
from core.domain.agent.router import RequestRoutingService, RouteDecision, RoutingKeywordConfig
from core.domain.agent.strategy import select_task_profile


# ---------------- #5 错误分类一致性 ----------------
def test_policy_400_consistent_not_retryable():
    # 修复前 is_retryable_error("400 Bad Request") 为 True（漏了 400），
    # classify_error 归为 validation（不可重试）→ 结论相反。现必须一致。
    assert classify_error("400 Bad Request") == "validation"
    assert is_retryable_error("400 Bad Request") is False
    assert classify_error("401 Unauthorized") == "auth"
    assert is_retryable_error("401 Unauthorized") is False
    assert classify_error("403 Forbidden") == "permission"
    assert is_retryable_error("403 Forbidden") is False
    assert classify_error("404 Not Found") == "not_found"
    assert is_retryable_error("404 Not Found") is False


def test_policy_retryable_categories():
    assert classify_error("500 Internal Error") == "upstream"
    assert is_retryable_error("500 Internal Error") is True
    assert classify_error("timed out") == "timeout"
    assert is_retryable_error("timed out") is True


# ---------------- #1 多步计划 + 预算 ----------------
def test_planner_multistep_content_generation():
    steps = build_initial_steps("content_generation", has_attachments=False, has_active_kb=True)
    assert [s.step_type for s in steps] == ["knowledge_retrieval", "draft", "review"]
    assert all(isinstance(s, PlanStep) for s in steps)


def test_planner_max_steps_cap():
    steps = build_initial_steps("content_generation", has_attachments=False, has_active_kb=True, max_steps=2)
    assert len(steps) == 2
    steps2 = build_initial_steps("rag_qa", has_attachments=True, has_active_kb=True, max_steps=1)
    assert len(steps2) == 1


def test_planner_decide_followup_retry_then_fallback():
    assert decide_followup("failed", 0, 2)["step_type"] == "retry_decision"
    assert decide_followup("failed", 2, 2)["step_type"] == "fallback_finalize"
    assert decide_followup("success", 0, 2)["step_type"] == "finalize_response"


# ---------------- #3 路由否定词 + 置信度 ----------------
def _router_with_config():
    cfg = RoutingKeywordConfig(
        pdf=("pdf", "PDF"),
        ppt=("ppt", "PPT"),
        summary=("总结",),
        generation=("生成", "写一份"),
        rag_hint=("如何",),
        fallback=("你好",),
        negation=("不要生成", "不要做PPT"),
    )
    return RequestRoutingService(cfg)


def test_router_negation_suppresses_generation():
    svc = _router_with_config()
    assert (
        svc.decide(query="不要生成PDF格式的说明书", has_attachments=False, has_active_kb=False).route
        != "pdf_generation"
    )
    assert (
        svc.decide(query="生成一份PDF培训方案", has_attachments=False, has_active_kb=False).route
        == "pdf_generation"
    )


def test_router_confidence_sort():
    svc = _router_with_config()
    # pdf(0.98) 应胜出 generation(0.92)
    assert (
        svc.decide(query="生成PDF格式的ppt课件", has_attachments=False, has_active_kb=False).route
        == "pdf_generation"
    )


def test_router_no_match_fallback():
    svc = _router_with_config()
    d = svc.decide(query="随便聊聊", has_attachments=False, has_active_kb=False)
    assert d.route == "fallback_chat"


# ---------------- #6 strategy 合并重复 if ----------------
def test_strategy_merged_duplicate_if_once():
    prof = select_task_profile(route="content_generation", query="帮我写一份允许联网搜索的培训方案")
    assert prof.evidence_policy == "internal_first_external_supplement"
    assert prof.search_focus_rule == "focus_entities_in_materials"
    marker = "当 knowledge_retrieval 返回未找到相关信息"
    # 重复 if 合并后，该约束只出现一次
    assert sum(1 for c in prof.constraints if c.startswith(marker)) == 1


# ---------------- #2 Runner 失败语义 + #1 预算 ----------------
def test_runner_plan_step_error_keeps_running():
    run = AgentRunState(run_id="x", goal="g", budget_remaining=5)
    run.plan_snapshot = {"steps": [{"step_id": "step-1", "step_type": "rag_qa", "step_goal": "x"}]}
    run.current_step = "step-1"
    step = AgentStepState(step_id="step-1", step_type="rag_qa", step_goal="x")
    AgentRunner().complete_step(run, step, output="", error="500 upstream failure")
    assert run.status == "running"  # 失败保留 running，决策权交 Planner
    assert run.next_step is None
    assert run.budget_remaining == 4  # 预算递减


def test_runner_finalize_step_error_terminal():
    run = AgentRunState(run_id="x", goal="g", budget_remaining=3)
    run.plan_snapshot = {"steps": []}
    step = AgentStepState(step_id="finalize-1", step_type="finalize_response", step_goal="x")
    AgentRunner().complete_step(run, step, output="", error="boom")
    assert run.status == "failed"
    assert run.next_step == "done"


# ---------------- 应用层门面委托 ----------------
@pytest.mark.asyncio
async def test_agent_planner_facade_multistep():
    class FakeRouter:
        async def decide(self, *, query, has_attachments, has_active_kb):
            return RouteDecision("content_generation", "rule", "x", 0.9)

    planner = AgentPlanner(FakeRouter(), max_steps=5)
    plan = await planner.build_initial_plan(query="q", has_attachments=False, has_active_kb=True)
    assert len(plan["steps"]) == 3
    assert plan["route_decision"].route == "content_generation"
