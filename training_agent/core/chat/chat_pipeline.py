"""Chat pipeline: core chat orchestration logic.

This module contains the main chat processing pipeline, extracted from
api/routers/chat.py to reduce cyclomatic complexity in the router layer.
"""

import uuid
import json
import time
import asyncio
import logging

from fastapi.responses import StreamingResponse

from api.deps import DBSession, CurrentUser
from api.schemas.chat import ChatStreamChunk
from core.config import settings
from core.exceptions import NotFoundException, ValidationException
from core.chat.rag_flow import RagRetrievalRequest, retrieve_chat_context
from core.llm.factory import get_llm_client
from core.chat.routing_flow import (
    RoutingRequest,
    initialize_chat_routing,
)
from core.chat.stream_events import format_sse_chunk
from core.agent.persistence import (
    persist_initial_agent_run,
    persist_agent_step_result,
    update_main_step_output,
    persist_finalize_step,
)
from core.chat.attachment_service import parse_attachments
from core.chat.conversation_service import (
    validate_conversation,
    save_user_message,
    get_history_messages,
)
from core.chat.web_search_state import (
    process_web_search_explicit_keyword,
    handle_ask_pending_response,
    process_kb_miss,
)
from core.chat.chat_context import build_material_text
from core.chat.chat_state import ChatRuntimeState
from core.chat.artifact_flow import (
    ArtifactStepContext,
    ArtifactGenerationRequest,
    generate_route_artifact,
)
from core.chat.answer_flow import (
    AnswerStepContext,
    AnswerGenerationRequest,
    AnswerStreamState,
    stream_answer_chunks,
)
from core.chat.autonomous_flow import (
    AutonomousExecutionRequest,
    AutonomousExecutionState,
    stream_autonomous_execution,
)
from core.chat.finalize_flow import (
    FinalizeFlowRequest,
    FinalizeFlowState,
    stream_finalize_flow,
)
from core.chat.completion_flow import (
    CompletionRequest,
    complete_chat_response,
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

            routing_result = await initialize_chat_routing(
                request=RoutingRequest(
                    query=message,
                    has_attachments=bool(all_attachments),
                    has_active_kb=bool(state.active_kb_id),
                ),
            )

            orchestrator = routing_result.orchestrator
            agent_run_state = routing_result.agent_run_state
            agent_step_state = routing_result.agent_step_state
            route_decision = routing_result.route_decision
            task_profile = routing_result.task_profile
            timings.update(routing_result.timings)

            persistence_ids = await persist_initial_agent_run(
                db=db,
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                conversation_id=conv.id,
                route=route_decision.route,
                agent_run_state=agent_run_state,
                agent_step_state=agent_step_state,
            )

            logger.info(
                f"[Timing] 路由决策完成: {timings['routing_ms']}ms, "
                f"route={route_decision.route}, source={route_decision.decision_source}"
            )
            logger.info(
                f"[Route] route={route_decision.route}, source={route_decision.decision_source}, "
                f"reason={route_decision.reason}, confidence={route_decision.confidence:.2f}"
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
                    autonomous_state = AutonomousExecutionState()

                    async for chunk in stream_autonomous_execution(
                        llm=llm,
                        request=AutonomousExecutionRequest(
                            query=user_message_text,
                            history_messages=[
                                {"role": msg.role, "content": msg.content}
                                for msg in history_messages[-6:]
                            ],
                            tenant_id=current_user.tenant_id,
                            conversation_title=conv.title or "知识整理",
                            active_kb_id=str(state.active_kb_id) if state.active_kb_id else None,
                            active_kb_name=state.active_kb_name,
                            web_search_enabled=(
                                task_profile.allow_external_search
                                or state.web_search_mode == "on"
                            ),
                            task_profile=task_profile,
                        ),
                        state=autonomous_state,
                    ):
                        if chunk:
                            full_content += chunk
                            yield format_sse_chunk(
                                content=chunk,
                                citations=[],
                                finished=False,
                                attachment_used=state.attachment_used,
                            )

                    timings.update(autonomous_state.timings)
                    artifacts.extend(autonomous_state.artifacts)
                    agent_step_state.tool_trace.extend(autonomous_state.tool_trace)

                    for artifact in autonomous_state.artifacts:
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
                    answer_state = AnswerStreamState()
                    async for chunk in stream_answer_chunks(
                        llm=llm,
                        request=AnswerGenerationRequest(
                            route=route_decision.route,
                            user_message_text=user_message_text,
                            material_text=material_text,
                            source_hint=source_hint,
                            chunks_data=chunks_data,
                            has_attachments=bool(all_attachments),
                            history_messages=[
                                {"role": msg.role, "content": msg.content}
                                for msg in history_messages[-6:]
                            ],
                            step_context=AnswerStepContext(
                                goal=agent_run_state.goal,
                                plan_snapshot=agent_run_state.plan_snapshot,
                                current_step=agent_run_state.current_step or "step-1",
                                next_step=agent_run_state.next_step,
                                completed_steps_summary=agent_run_state.completed_steps_summary,
                                available_tools=available_tools,
                            ),
                        ),
                        state=answer_state,
                    ):
                        if chunk:
                            full_content += chunk
                            yield format_sse_chunk(
                                content=chunk,
                                citations=[],
                                finished=False,
                                attachment_used=state.attachment_used,
                            )
                    timings.update(answer_state.timings)
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

            # Dynamic follow-up step (retry / finalize)
            finalize_state = FinalizeFlowState()

            async for chunk in stream_finalize_flow(
                llm=llm,
                orchestrator=orchestrator,
                agent_run_state=agent_run_state,
                agent_step_state=agent_step_state,
                request=FinalizeFlowRequest(
                    user_message_text=user_message_text,
                    history_messages=[
                        {"role": msg.role, "content": msg.content}
                        for msg in history_messages[-4:]
                    ],
                    available_tools=available_tools,
                    artifacts=artifacts,
                ),
                state=finalize_state,
            ):
                if chunk:
                    yield format_sse_chunk(
                        content=chunk,
                        citations=[],
                        finished=False,
                        attachment_used=state.attachment_used,
                    )

            if finalize_state.content_suffix:
                full_content += finalize_state.content_suffix

            if finalize_state.finalize_step_state is not None:
                persistence_ids = await persist_finalize_step(
                    db=db,
                    ids=persistence_ids,
                    agent_run_state=agent_run_state,
                    finalize_step_state=finalize_state.finalize_step_state,
                )

            # retry 成功后更新主 step output
            if finalize_state.finalize_trace:
                final_trace_types = [t.get("type") for t in finalize_state.finalize_trace]
                if "retry" in final_trace_types and not finalize_state.error:
                    await update_main_step_output(
                        db=db,
                        step_db_id=persistence_ids.step_db_id,
                        output=full_content,
                    )

            completion_result = await complete_chat_response(
                db=db,
                request=CompletionRequest(
                    conversation_id=conv.id,
                    content=full_content,
                    citations=citations_list,
                    route=route_decision.route,
                    decision_source=route_decision.decision_source,
                    reason=route_decision.reason,
                    confidence=route_decision.confidence,
                    agent_run_id=agent_run_state.run_id,
                    agent_run_db_id=str(persistence_ids.run_db_id) if persistence_ids.run_db_id else None,
                    agent_status=agent_run_state.status,
                    agent_current_step=agent_run_state.current_step,
                    agent_next_step=agent_run_state.next_step,
                    completed_steps_summary=agent_run_state.completed_steps_summary,
                    artifacts=artifacts,
                    timings=timings,
                    attachment_used=state.attachment_used,
                    web_search_mode=state.web_search_mode,
                    started_at=t_total,
                ),
            )

            logger.info(
                f"[Timing] 总耗时: {completion_result.latency_ms}ms, "
                f"routing={route_decision.route}, retrieval_ms={timings.get('retrieval_ms', 0)}, "
                f"attachments={len(all_attachments)}, citations={len(citations_list)}"
            )

            yield format_sse_chunk(
                content="",
                citations=[],
                finished=False,
                attachment_used=state.attachment_used,
                agent=completion_result.agent_payload,
            )
            yield format_sse_chunk(
                content="",
                citations=[],
                finished=True,
                attachment_used=state.attachment_used,
                web_search_mode=completion_result.finished_payload["web_search_mode"],
            )

    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
