"""Chat pipeline: core chat orchestration logic.

This module contains the main chat processing pipeline, extracted from
api/routers/chat.py to reduce cyclomatic complexity in the router layer.
"""

import uuid
import json
import time
import asyncio
import logging
from datetime import datetime

from fastapi.responses import StreamingResponse

from api.deps import DBSession, CurrentUser
from api.schemas.chat import ChatStreamChunk
from core.config import settings
from core.exceptions import NotFoundException, ValidationException
from core.chat.rag_flow import RagRetrievalRequest, retrieve_chat_context
from core.agent.orchestrator import AgentOrchestrator
from core.agent.request_router import RequestRouter
from core.agent.executor import AgentStepExecutor
from core.agent.strategy import select_task_profile
from core.tools.registry import ToolRegistry
from core.tools.knowledge_tool import KnowledgeRetrievalTool
from core.tools.solution_tool import SolutionGeneratorTool
from core.tools.web_search_tool import WebSearchTool
from core.tools.ppt_tool import PPTGenerationTool
from core.tools.pdf_export_tool import PDFExportTool
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
from core.prompts.agent import build_step_execution_prompt, SOLUTION_AGENT_PROMPT
from core.chat.stream_events import stream_llm_response, format_sse_chunk
from core.chat.attachment_service import parse_attachments
from core.chat.conversation_service import (
    validate_conversation,
    save_user_message,
    get_history_messages,
    save_assistant_message,
)
from core.chat.web_search_state import (
    process_web_search_explicit_keyword,
    handle_ask_pending_response,
    process_kb_miss,
)
from core.chat.chat_context import build_context_from_chunks, build_material_text
from core.chat.chat_state import ChatRuntimeState
from core.llm.factory import get_llm_client
from core.agent.persistence import (
    persist_initial_agent_run,
    persist_agent_step_result,
    update_main_step_output,
    persist_finalize_step,
)
from core.chat.artifact_flow import (
    ArtifactStepContext,
    ArtifactGenerationRequest,
    generate_route_artifact,
)
from models.tables import KnowledgeBase

logger = logging.getLogger(__name__)

CHAT_PIPELINE_SEMAPHORE = asyncio.Semaphore(settings.chat_request_concurrency)
ATTACHMENT_PARSE_SEMAPHORE = asyncio.Semaphore(settings.attachment_parse_concurrency)


def _should_use_autonomous_tool_mode(
    *,
    route: str,
    has_attachments: bool,
    allow_external_search: bool = False,
) -> bool:
    if has_attachments:
        return False
    if route in {"content_generation", "pdf_generation", "ppt_generation"}:
        return True
    if route == "rag_qa" and allow_external_search:
        return True
    return False


async def handle_chat(
    conversation_id: str,
    message: str,
    knowledge_base_id_str: str | None,
    files: list,
    db: DBSession,
    current_user: CurrentUser,
    web_search: bool | None = None,
):
    """Core chat logic shared by both JSON and form-data routes."""
    # Filter out empty file entries
    valid_files = [f for f in files if f.filename]
    logger.info(f"[Chat] 进入对话函数, conv_id={conversation_id}, msg={message[:50]}, file_count={len(valid_files)}")

    # Validate conversation
    conv = await validate_conversation(conversation_id, db, current_user)
    logger.info(f"[Chat] 对话验证通过, conv_id={conversation_id}, title={conv.title}")

    # Parse attachments if provided
    all_attachments = await parse_attachments(
        valid_files, ATTACHMENT_PARSE_SEMAPHORE,
        current_user.tenant_id, conversation_id,
    )

    requested_kb_id = uuid.UUID(knowledge_base_id_str) if knowledge_base_id_str else None
    initial_active_kb_id = requested_kb_id or conv.knowledge_base_id
    if requested_kb_id:
        from core.permissions import require_visible_kb
        await require_visible_kb(db, current_user, requested_kb_id)
    elif initial_active_kb_id:
        from core.permissions import visible_knowledge_base_query
        result = await db.execute(
            visible_knowledge_base_query(current_user).where(
                KnowledgeBase.id == initial_active_kb_id
            )
        )
        if not result.scalar_one_or_none():
            initial_active_kb_id = None
    logger.info(f"[Chat] kb_id={initial_active_kb_id}")

    # Get history messages
    history_messages = await get_history_messages(conv.id, db)

    # Build user message (with attachment injection)
    if all_attachments:
        blocks = []
        for fname, fcontent in all_attachments:
            blocks.append(f"[用户上传附件]\n文件名：{fname}\n内容：\n{fcontent}\n---")
        user_message_text = "\n\n".join(blocks) + "\n\n" + message
    else:
        user_message_text = message

    # Save user message to DB (original message, not with attachment prefix)
    logger.info(f"[Chat] 保存用户消息")
    await save_user_message(conv.id, message, db)

    # === 初始化运行时状态(替代内嵌闭包里的 mutable 变量) ===
    conv_meta = dict(conv.meta or {})
    state = ChatRuntimeState(
        web_search_mode=conv_meta.get("web_search_mode", "off"),
        conv_meta=conv_meta,
        active_kb_id=initial_active_kb_id,
        active_kb_name="知识库",
        attachment_used=bool(all_attachments),
    )

    # Frontend toggle button takes priority
    if web_search is not None:
        state.web_search_mode = "on" if web_search else "off"
        state.conv_meta["web_search_mode"] = state.web_search_mode
        state.conv_meta.pop("ask_pending", None)
        state.conv_meta.pop("pending_ask_query", None)
        conv.meta = state.conv_meta
        db.add(conv)
        await db.commit()

    # Explicit keyword detection
    if state.web_search_mode != "on":
        process_web_search_explicit_keyword(message, state.conv_meta)
        if state.conv_meta.get("web_search_mode") == "on":
            state.web_search_mode = "on"
            conv.meta = state.conv_meta
            db.add(conv)
            await db.commit()

    # Ask-pending: user replied to "是否允许联网搜索"
    handled, response, new_mode = await handle_ask_pending_response(
        message, state.conv_meta, conv, db,
    )
    if handled:
        state.web_search_mode = new_mode
        return response

    async def generate_response():
        async with CHAT_PIPELINE_SEMAPHORE:
            t_total = time.time()
            full_content = ""
            citations_list = state.citations
            artifacts: list[dict] = state.artifacts
            timings: dict[str, int] = state.timings

            t0 = time.time()
            from core.permissions import visible_knowledge_base_query
            kb_result = await db.execute(visible_knowledge_base_query(current_user))
            all_kbs = kb_result.scalars().all()
            active_kb_name = next(
                (kb.name for kb in all_kbs if state.active_kb_id and kb.id == state.active_kb_id),
                "知识库",
            )
            state.active_kb_name = active_kb_name
            timings["visible_kb_ms"] = int((time.time() - t0) * 1000)
            logger.info(f"[Timing] 查询知识库列表: {timings['visible_kb_ms']}ms, count={len(all_kbs)}")

            t0 = time.time()
            # 业务层不再感知 provider / api_key / base_url,统一通过工厂取
            router_llm = get_llm_client("classify")
            router = RequestRouter(router_llm)
            orchestrator = AgentOrchestrator(router)
            agent_run_state, agent_plan = await orchestrator.start_run(
                query=message,
                has_attachments=bool(all_attachments),
                has_active_kb=bool(state.active_kb_id),
            )
            route_decision = agent_run_state.route_decision
            if route_decision is None:
                route_decision = await router.decide(
                    query=message,
                    has_attachments=bool(all_attachments),
                    has_active_kb=bool(state.active_kb_id),
                )
                agent_run_state.route_decision = route_decision
                agent_run_state.plan_snapshot = {
                    "steps": [{"step_id": "step-1", "step_type": route_decision.route, "step_goal": f"execute_{route_decision.route}"}],
                    "route": route_decision.route,
                }

            first_step = (
                agent_plan["steps"][0]
                if agent_plan.get("steps")
                else {"step_id": "step-1", "step_type": route_decision.route, "step_goal": f"execute_{route_decision.route}"}
            )
            agent_step_state = orchestrator.runner.start_step(agent_run_state, first_step)
            persistence_ids = await persist_initial_agent_run(
                db=db,
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                conversation_id=conv.id,
                route=route_decision.route,
                agent_run_state=agent_run_state,
                agent_step_state=agent_step_state,
            )
            timings["routing_ms"] = int((time.time() - t0) * 1000)
            logger.info(
                f"[Timing] 路由决策完成: {timings['routing_ms']}ms, "
                f"route={route_decision.route}, source={route_decision.decision_source}"
            )
            logger.info(
                f"[Route] route={route_decision.route}, source={route_decision.decision_source}, "
                f"reason={route_decision.reason}, confidence={route_decision.confidence:.2f}"
            )
            task_profile = select_task_profile(
                route=route_decision.route,
                query=message,
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

            chunks_data = state.chunks_data
            timings["embedding_ms"] = 0
            timings["retrieval_ms"] = 0

            # === RAG 检索:通过 rag_flow 统一入口 ===
            rag_result = await retrieve_chat_context(
                db=db,
                request=RagRetrievalRequest(
                    query=message,
                    active_kb_id=state.active_kb_id,
                    route=route_decision.route,
                ),
            )
            state.chunks_data.extend(rag_result.chunks_data)
            state.citations.extend(rag_result.citations)
            timings.update(rag_result.timings)
            # 同步本地变量,避免后面再回读
            chunks_data = state.chunks_data

            if state.active_kb_id:
                logger.info(f"[Timing] kb_id={str(state.active_kb_id)[:8]}..., chunks={len(state.chunks_data)}")

            # === KB miss handling:写回 state.web_search_mode(无 nonlocal) ===
            if state.active_kb_id and not state.chunks_data and not all_attachments:
                new_mode = process_kb_miss(
                    active_kb_id=bool(state.active_kb_id),
                    chunks_data=state.chunks_data,
                    all_attachments=all_attachments,
                    web_search_mode=state.web_search_mode,
                    conv_meta=state.conv_meta,
                    pending_query=message,
                )
                if new_mode != state.web_search_mode:
                    state.web_search_mode = new_mode
                    conv.meta = state.conv_meta
                    db.add(conv)
                    await db.commit()
            elif state.active_kb_id and state.chunks_data:
                if state.conv_meta.get("kb_miss_count", 0) > 0:
                    state.conv_meta["kb_miss_count"] = 0
                    conv.meta = state.conv_meta
                    db.add(conv)
                    await db.commit()

            # 业务层不再感知 model / base_url / provider,通过工厂按 purpose 取
            llm = get_llm_client("chat")
            chat_model = llm.model  # 仅用于日志

            t_context = time.time()
            material_text, source_hint = build_material_text(all_attachments, chunks_data)
            autonomous_tool_mode = _should_use_autonomous_tool_mode(
                route=route_decision.route,
                has_attachments=bool(all_attachments),
                allow_external_search=(task_profile.allow_external_search or state.web_search_mode == "on"),
            )
            available_tools = ["knowledge_retrieval", "solution_generator", "ppt_generation", "pdf_export"]
            if autonomous_tool_mode and (task_profile.allow_external_search or state.web_search_mode == "on"):
                available_tools.insert(1, "web_search")
            timings["context_build_ms"] = int((time.time() - t_context) * 1000)
            logger.info(
                f"[Timing] 上下文构建完成: attachments={len(all_attachments)}, "
                f"chunks={len(chunks_data)}, material_len={len(material_text)}, "
                f"source_hint={source_hint}, has_material={bool(material_text)}"
            )

            try:
                if "[FORCE_AGENT_STEP1_FAIL]" in (message or ""):
                    raise RuntimeError("forced_step1_failure_for_mvp_regression")
                if autonomous_tool_mode:
                    registry = ToolRegistry()
                    if state.active_kb_id:
                        registry.register(
                            KnowledgeRetrievalTool(
                                kb_id=str(state.active_kb_id),
                                kb_name=state.active_kb_name,
                            )
                        )
                    if task_profile.allow_external_search or state.web_search_mode == "on":
                        registry.register(WebSearchTool())
                    registry.register(SolutionGeneratorTool(llm))
                    registry.register(PPTGenerationTool(tenant_id=current_user.tenant_id))
                    registry.register(PDFExportTool(tenant_id=current_user.tenant_id))

                    if state.web_search_mode == "on" or task_profile.allow_external_search:
                        autonomous_system_prompt = (
                            f"{SOLUTION_AGENT_PROMPT}\n\n"
                            f"当前状态：web_search 工具已就绪。"
                        )
                    else:
                        autonomous_system_prompt = (
                            "你是一个个人 AI 知识库助手自治执行器。\n"
                            f"{task_profile.build_instruction()}\n"
                            "必须严格围绕当前目标选择工具。"
                        )

                    executor = AgentStepExecutor(
                        llm_client=llm,
                        registry=registry,
                        system_prompt=autonomous_system_prompt,
                        max_iterations=settings.max_iterations,
                    )
                    t0 = time.time()
                    logger.info(
                        f"[Timing] 自治Agent工具链开始, route={route_decision.route}, "
                        f"tools={registry.list_tools()}"
                    )
                    async for chunk in executor.run(query=user_message_text, history=[
                        {"role": msg.role, "content": msg.content}
                        for msg in history_messages[-6:]
                    ]):
                        if chunk:
                            if "llm_first_token_ms" not in timings:
                                timings["llm_first_token_ms"] = int((time.time() - t0) * 1000)
                            full_content += chunk
                            yield format_sse_chunk(content=chunk, citations=[], finished=False, attachment_used=state.attachment_used)
                    timings["llm_total_ms"] = int((time.time() - t0) * 1000)
                    artifacts.extend(executor.artifacts)
                    agent_step_state.tool_trace.extend(executor.tool_trace)
                    if (
                        task_profile.artifact_required
                        and not artifacts
                        and full_content
                        and "请提供" not in full_content
                        and "资料不足" not in full_content
                        and "生成回答时出现错误" not in full_content
                    ):
                        registry_tool = registry.get(task_profile.artifact_tool or "")
                        if registry_tool:
                            artifact_result_raw = registry_tool.invoke(
                                content=full_content,
                                title=conv.title or "知识整理",
                            )
                            agent_step_state.tool_trace.append(
                                {
                                    "type": "task_profile_enforced_tool",
                                    "tool_name": task_profile.artifact_tool,
                                    "goal_type": task_profile.goal_type,
                                    "content_type": task_profile.content_type,
                                    "result_preview": artifact_result_raw[:500],
                                }
                            )
                            try:
                                artifact_result = json.loads(artifact_result_raw)
                            except json.JSONDecodeError:
                                artifact_result = {}
                            task_id = artifact_result.get("task_id")
                            if task_id:
                                artifact_type = "pdf" if task_profile.artifact_tool == "pdf_export" else "ppt"
                                artifacts.append({"type": artifact_type, "task_id": task_id})
                    for artifact in artifacts:
                        yield format_sse_chunk(
                            content="",
                            citations=[],
                            finished=False,
                            attachment_used=state.attachment_used,
                            artifact=artifact,
                            ppt_task_id=artifact["task_id"] if artifact["type"] == "ppt" else None,
                            pdf_task_id=artifact["task_id"] if artifact["type"] == "pdf" else None,
                        )
                elif route_decision.route in {"ppt_generation", "pdf_generation"}:
                    artifact_result = await generate_route_artifact(
                        llm=llm,
                        request=ArtifactGenerationRequest(
                            route=route_decision.route,
                            material_text=material_text,
                            message=message,
                            source_hint=source_hint,
                            conversation_title=conv.title or "知识整理",
                            tenant_id=current_user.tenant_id,
                            history_messages=[
                                {"role": msg.role, "content": msg.content}
                                for msg in history_messages[-6:]
                            ],
                            step_context=ArtifactStepContext(
                                goal=agent_run_state.goal,
                                plan_snapshot=agent_run_state.plan_snapshot,
                                current_step=agent_run_state.current_step or "step-1",
                                next_step=agent_run_state.next_step,
                                completed_steps_summary=agent_run_state.completed_steps_summary,
                                available_tools=available_tools,
                            ),
                        ),
                    )

                    full_content = artifact_result.content
                    artifacts.extend(artifact_result.artifacts)
                    timings.update(artifact_result.timings)

                    yield format_sse_chunk(
                        content=full_content,
                        citations=citations_list,
                        finished=False,
                        attachment_used=state.attachment_used,
                    )
                    for artifact in artifacts:
                        yield format_sse_chunk(
                            content="",
                            citations=[],
                            finished=False,
                            attachment_used=state.attachment_used,
                            artifact=artifact,
                            ppt_task_id=artifact["task_id"] if artifact["type"] == "ppt" else None,
                            pdf_task_id=artifact["task_id"] if artifact["type"] == "pdf" else None,
                        )
                else:
                    if route_decision.route == "document_summary":
                        system_prompt = build_document_summary_prompt(material_text or user_message_text, source_hint)
                    elif route_decision.route == "content_generation":
                        system_prompt = build_content_generation_prompt(material_text or user_message_text, source_hint)
                    elif route_decision.route == "rag_qa":
                        if all_attachments and chunks_data:
                            system_prompt = build_attachment_with_kb_prompt(build_context_from_chunks(chunks_data), source_type="local")
                        elif all_attachments:
                            system_prompt = build_attachment_only_prompt(source_type="local")
                        elif chunks_data:
                            system_prompt = build_kb_only_prompt(build_context_from_chunks(chunks_data))
                        else:
                            system_prompt = FALLBACK_PROMPT
                    else:
                        system_prompt = FALLBACK_CHAT_SYSTEM_PROMPT

                    step_prompt = build_step_execution_prompt(
                        base_system_prompt=system_prompt,
                        goal=agent_run_state.goal,
                        plan_snapshot=agent_run_state.plan_snapshot,
                        current_step=agent_run_state.current_step or "step-1",
                        next_step=agent_run_state.next_step,
                        completed_steps_summary=agent_run_state.completed_steps_summary,
                        available_tools=available_tools,
                    )
                    llm_messages = [{"role": "system", "content": step_prompt}]
                    for msg in history_messages[-6:]:
                        llm_messages.append({"role": msg.role, "content": msg.content})
                    llm_messages.append({"role": "user", "content": user_message_text})

                    logger.info(
                        f"[Timing] 调用LLM开始, route={route_decision.route}, model={chat_model}, messages={len(llm_messages)}"
                    )
                    t0 = time.time()
                    first_chunk_time = None
                    async for chunk in stream_llm_response(llm, llm_messages, temperature=0.1):
                        if chunk:
                            if first_chunk_time is None:
                                first_chunk_time = time.time()
                                timings["llm_first_token_ms"] = int((first_chunk_time - t0) * 1000)
                                logger.info(f"[Timing] LLM首token: {timings['llm_first_token_ms']}ms")
                            full_content += chunk
                            yield format_sse_chunk(content=chunk, citations=[], finished=False, attachment_used=state.attachment_used)
                    timings["llm_total_ms"] = int((time.time() - t0) * 1000)
                    logger.info(f"[Timing] LLM响应完成: {timings['llm_total_ms']}ms, chars={len(full_content)}")
                    # Ask-pending: append gentle ask to response
                    if state.web_search_mode == "ask_pending":
                        ask_text = '\n\n---\n知识库暂无相关信息，是否允许我开启联网搜索？（回复"好的"开启，或说"不用了"）'
                        full_content += ask_text
                        yield format_sse_chunk(content=ask_text, citations=[], finished=False, attachment_used=state.attachment_used)
            except Exception as e:
                logger.error(f"[Timing] LLM调用失败: {e}", exc_info=True)
                err_msg = str(e)
                err_type = orchestrator.policy.classify_error(err_msg)
                fallback = orchestrator.policy.fallback_message_for(err_type)
                yield format_sse_chunk(content=fallback, citations=[], finished=False, attachment_used=state.attachment_used)
                full_content = fallback
                orchestrator.runner.complete_step(
                    agent_run_state,
                    agent_step_state,
                    output=full_content,
                    artifacts=artifacts,
                    error=f"{err_type}:{err_msg}",
                )
            else:
                orchestrator.runner.complete_step(
                    agent_run_state,
                    agent_step_state,
                    output=full_content,
                    artifacts=artifacts,
                )
            agent_tool_trace = list(agent_step_state.tool_trace or [])
            agent_tool_trace.extend([
                {
                    "type": "route",
                    "route": route_decision.route,
                    "decision_source": route_decision.decision_source,
                    "reason": route_decision.reason,
                    "confidence": route_decision.confidence,
                },
                {
                    "type": "retrieval",
                    "citations_count": len(citations_list),
                    "chunks_count": len(chunks_data),
                    "timings": timings,
                },
            ])
            if artifacts:
                agent_tool_trace.append({"type": "artifacts", "items": artifacts})
            if agent_step_state.status == "failed" and agent_step_state.error:
                step_error_type = orchestrator.policy.classify_error(agent_step_state.error)
                agent_tool_trace.append({"type": "error", "error_type": step_error_type, "message": agent_step_state.error[:1000]})
                agent_run_state.last_error = f"{step_error_type}:{agent_step_state.error[:1000]}"
            agent_step_state.tool_trace = agent_tool_trace
            await persist_agent_step_result(
                db=db,
                ids=persistence_ids,
                agent_run_state=agent_run_state,
                agent_step_state=agent_step_state,
            )

            # Dynamic follow-up step
            followup_step_def = orchestrator.planner.build_followup_step(
                agent_run_state,
                agent_step_state,
                max_retries=orchestrator.policy.max_retries,
            )
            if followup_step_def:
                snapshot_steps = (agent_run_state.plan_snapshot or {}).get("steps", [])
                snapshot_steps.append(followup_step_def)
                agent_run_state.plan_snapshot["steps"] = snapshot_steps

                finalize_step_state = orchestrator.runner.start_step(agent_run_state, followup_step_def)
                finalize_output = "agent_finalize_completed"
                finalize_already_completed = False
                finalize_trace: list[dict] = [
                    {"type": "followup", "step_type": followup_step_def.get("step_type"), "step_goal": followup_step_def.get("step_goal")}
                ]
                if followup_step_def.get("step_type") == "retry_decision":
                    retry_output = ""
                    retry_error = ""
                    remaining_attempts = max(1, orchestrator.policy.max_retries - agent_run_state.retry_count + 1)
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
                                available_tools=available_tools,
                            )
                            retry_messages = [{"role": "system", "content": retry_system_prompt}]
                            for msg in history_messages[-4:]:
                                retry_messages.append({"role": msg.role, "content": msg.content})
                            retry_messages.append({"role": "user", "content": user_message_text})
                            async for chunk in stream_llm_response(llm, retry_messages, temperature=0.1):
                                if chunk:
                                    retry_output += chunk
                                    yield format_sse_chunk(content=chunk, citations=[], finished=False, attachment_used=state.attachment_used)
                            if retry_output:
                                break
                            retry_error = "retry_empty_output"
                        except Exception as retry_exc:
                            retry_error = str(retry_exc)
                        if retry_error and attempt < remaining_attempts and orchestrator.policy.is_retryable_error(retry_error):
                            delay = orchestrator.policy.retry_backoff_seconds(attempt)
                            finalize_trace.append(
                                {"type": "retry_backoff", "attempt": attempt, "delay_sec": round(delay, 3), "error": retry_error[:200]}
                            )
                            await asyncio.sleep(delay)
                    if retry_output:
                        full_content = f"{full_content}\n\n[重试结果]\n{retry_output}"
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
                        full_content = f"{full_content}\n\n{fallback_on_retry}"
                        orchestrator.runner.complete_step(
                            agent_run_state,
                            finalize_step_state,
                            output=finalize_output,
                            tool_trace=finalize_trace + [{"type": "artifacts", "items": artifacts}],
                            error=f"{retry_error_type}:{retry_error}",
                        )
                        agent_run_state.last_error = f"{retry_error_type}:{retry_error[:1000]}"
                        finalize_already_completed = True
                    else:
                        orchestrator.runner.complete_step(
                            agent_run_state,
                            finalize_step_state,
                            output=finalize_output,
                            tool_trace=finalize_trace + [{"type": "artifacts", "items": artifacts}],
                        )
                        finalize_already_completed = True
                        await update_main_step_output(
                            db=db,
                            step_db_id=persistence_ids.step_db_id,
                            output=full_content,
                        )
                if followup_step_def.get("step_type") == "fallback_finalize":
                    finalize_output = "fallback_finalize_completed"
                    finalize_trace.append({"type": "fallback", "message": "reroute_to_safe_fallback_response"})
                if finalize_step_state is not None and not finalize_already_completed:
                    orchestrator.runner.complete_step(
                        agent_run_state,
                        finalize_step_state,
                        output=finalize_output,
                        tool_trace=finalize_trace + [{"type": "artifacts", "items": artifacts}],
                    )
                persistence_ids = await persist_finalize_step(
                    db=db,
                    ids=persistence_ids,
                    agent_run_state=agent_run_state,
                    finalize_step_state=finalize_step_state,
                )

            latency_ms = int((time.time() - t_total) * 1000)
            timings["total_ms"] = latency_ms
            logger.info(
                f"[Timing] 总耗时: {latency_ms}ms, "
                f"routing={route_decision.route}, retrieval_ms={timings.get('retrieval_ms', 0)}, "
                f"attachments={len(all_attachments)}, citations={len(citations_list)}"
            )

            await save_assistant_message(
                conversation_id=conv.id,
                content=full_content,
                citations=citations_list,
                context={
                    "route": route_decision.route,
                    "decision_source": route_decision.decision_source,
                    "reason": route_decision.reason,
                    "confidence": route_decision.confidence,
                    "agent": {
                        "run_id": agent_run_state.run_id,
                        "run_db_id": str(persistence_ids.run_db_id) if persistence_ids.run_db_id else None,
                        "status": agent_run_state.status,
                        "current_step": agent_run_state.current_step,
                        "next_step": agent_run_state.next_step,
                        "completed_steps_summary": agent_run_state.completed_steps_summary,
                    },
                    "artifacts": artifacts,
                    "timings": timings,
                },
                token_count=len(full_content.split()),
                latency_ms=latency_ms,
                db=db,
            )

            yield format_sse_chunk(content="", citations=[], finished=False, attachment_used=state.attachment_used, agent={
                "run_id": agent_run_state.run_id,
                "run_db_id": str(persistence_ids.run_db_id) if persistence_ids.run_db_id else None,
                "status": agent_run_state.status,
                "current_step": agent_run_state.current_step,
                "next_step": agent_run_state.next_step,
                "completed_steps_summary": agent_run_state.completed_steps_summary,
            })
            yield format_sse_chunk(content="", citations=[], finished=True, attachment_used=state.attachment_used, web_search_mode=state.web_search_mode)

    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
