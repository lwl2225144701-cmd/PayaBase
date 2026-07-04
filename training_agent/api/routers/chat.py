import uuid
import logging
import time
import json
import asyncio
import threading
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select, func, update
from minio import Minio

from api.deps import DBSession, CurrentUser
from api.schemas.common import Response
from api.schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    ConversationListResponse,
    ChatRequest,
    ChatResponse,
    ChatStreamChunk,
    MessageResponse,
)
from core.exceptions import NotFoundException, ValidationException
from core.permissions import require_visible_kb, visible_knowledge_base_query
from core.rag.retriever import Retriever
from core.rag.instant_parser import InstantFileParser
from core.embedding.client import EmbeddingClient
from core.config import settings
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
    build_pdf_generation_prompt,
    build_ppt_generation_prompt,
    FALLBACK_CHAT_SYSTEM_PROMPT,
)
from core.prompts.agent import build_step_execution_prompt, SOLUTION_AGENT_PROMPT
from models.tables import Conversation, Message, KnowledgeBase, AgentRun, AgentStep

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_ATTACHMENT_TYPES = {"pdf", "docx", "doc", "txt", "md", "png", "jpg", "jpeg", "gif", "webp", "bmp"}
CHAT_PIPELINE_SEMAPHORE = asyncio.Semaphore(settings.chat_request_concurrency)
ATTACHMENT_PARSE_SEMAPHORE = asyncio.Semaphore(settings.attachment_parse_concurrency)


def _get_minio_client() -> Minio:
    """Create MinIO client from settings."""
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )


def _put_attachment_object(
    tenant_id: str,
    conversation_id: str,
    filename: str,
    content: bytes,
) -> str:
    from pathlib import Path
    import io

    minio_client = _get_minio_client()
    if not minio_client.bucket_exists(settings.minio_bucket):
        minio_client.make_bucket(settings.minio_bucket)

    safe_name = Path(filename).name
    key = f"{settings.temp_attachment_prefix}/{tenant_id}/{conversation_id}/{safe_name}"
    minio_client.put_object(
        settings.minio_bucket,
        key,
        data=io.BytesIO(content),
        length=len(content),
        content_type="application/octet-stream",
    )
    return key


async def _save_attachment_to_minio(
    tenant_id: str,
    conversation_id: str,
    filename: str,
    content: bytes,
) -> str:
    """Upload attachment to MinIO temp path.

    Returns:
        The MinIO object key
    """
    key = await asyncio.to_thread(
        _put_attachment_object,
        tenant_id,
        conversation_id,
        filename,
        content,
    )
    logger.info(f"[Chat] Attachment saved to MinIO: {key}")
    return key


async def _stream_sync_iterator(sync_iterable):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[object] = asyncio.Queue()
    sentinel = object()

    def worker():
        try:
            for item in sync_iterable:
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as exc:  # pragma: no cover - defensive
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        item = await queue.get()
        if item is sentinel:
            break
        if isinstance(item, Exception):
            raise item
        yield item


def _build_context_from_chunks(chunks_data: list[dict], limit: int = 5) -> str:
    context_parts = []
    for i, chunk in enumerate(chunks_data[:limit], 1):
        content_text = chunk["content"][:700]
        source = chunk.get("source", "未知来源")
        context_parts.append(f"【{i}】[{source}]\n{content_text}")
    return "\n\n".join(context_parts)


def _infer_primary_source_label(
    chunks_data: list[dict],
    has_attachments: bool,
) -> str:
    if has_attachments:
        return "用户上传附件"
    if not chunks_data:
        return "无资料"
    return chunks_data[0].get("source", "知识库文档")


async def _stream_llm_response(
    llm,
    messages: list[dict],
    *,
    temperature: float,
):
    async for chunk in _stream_sync_iterator(
        llm.stream_chat(messages, temperature=temperature)
    ):
        yield chunk


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


def _classify_yes_no(text: str) -> bool:
    """Quick yes/no classification for web search permission responses."""
    text = text.strip().lower()
    no_keywords = ("不用", "不要", "算了", "不必", "不了", "别", "不需要", "no", "不搜", "不查", "没必要", "不用了")
    for kw in no_keywords:
        if kw in text:
            return False
    yes_keywords = ("好", "可以", "嗯", "是的", "对", "搜", "查", "行", "ok", "好的", "好吧", "行吧", "搜搜", "查查", "看看", "开")
    for kw in yes_keywords:
        if kw in text:
            return True
    return False


@router.get("/conversations", response_model=Response[list[ConversationListResponse]])
async def list_conversations(
    db: DBSession,
    current_user: CurrentUser,
    page: int = 1,
    page_size: int = 20,
):
    query = (
        select(Conversation)
        .where(
            Conversation.tenant_id == uuid.UUID(current_user.tenant_id),
            Conversation.user_id == uuid.UUID(current_user.id),
        )
        .order_by(Conversation.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    conversations = result.scalars().all()

    items = []
    for conv in conversations:
        msg_count = await db.scalar(
            select(func.count()).select_from(Message).where(
                Message.conversation_id == conv.id
            )
        ) or 0
        items.append(
            ConversationListResponse(
                id=str(conv.id),
                title=conv.title,
                knowledge_base_id=str(conv.knowledge_base_id) if conv.knowledge_base_id else None,
                message_count=msg_count,
                created_at=conv.created_at,
            )
        )

    return Response(data=items)


@router.post("/conversations", response_model=Response[ConversationResponse])
async def create_conversation(
    data: ConversationCreate,
    db: DBSession,
    current_user: CurrentUser,
):
    kb_id = uuid.UUID(data.knowledge_base_id) if data.knowledge_base_id else None
    if kb_id:
        await require_visible_kb(db, current_user, kb_id)

    conv = Conversation(
        tenant_id=uuid.UUID(current_user.tenant_id),
        user_id=uuid.UUID(current_user.id),
        knowledge_base_id=kb_id,
        title=data.title,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return Response(
        data=ConversationResponse(
            id=str(conv.id),
            tenant_id=str(conv.tenant_id),
            user_id=str(conv.user_id),
            knowledge_base_id=str(conv.knowledge_base_id) if conv.knowledge_base_id else None,
            title=conv.title,
            message_count=0,
            created_at=conv.created_at,
        )
    )


@router.get("/conversations/{conversation_id}", response_model=Response[list[MessageResponse]])
async def get_conversation(
    conversation_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == uuid.UUID(conversation_id),
            Conversation.tenant_id == uuid.UUID(current_user.tenant_id),
            Conversation.user_id == uuid.UUID(current_user.id),
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundException("Conversation not found")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    items = [
        MessageResponse(
            id=str(msg.id),
            conversation_id=str(msg.conversation_id),
            role=msg.role,
            content=msg.content,
            citations=msg.citations or [],
            token_count=msg.token_count,
            created_at=msg.created_at,
        )
        for msg in messages
    ]

    return Response(data=items)


async def _handle_chat(
    conversation_id: str,
    message: str,
    knowledge_base_id_str: Optional[str],
    files: list[UploadFile],
    db: DBSession,
    current_user: CurrentUser,
    web_search: Optional[bool] = None,
):
    """Core chat logic shared by both JSON and form-data routes."""
    # Filter out empty file entries
    valid_files = [f for f in files if f.filename]
    logger.info(f"[Chat] 进入对话函数, conv_id={conversation_id}, msg={message[:50]}, file_count={len(valid_files)}")

    # Validate conversation
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == uuid.UUID(conversation_id),
            Conversation.tenant_id == uuid.UUID(current_user.tenant_id),
            Conversation.user_id == uuid.UUID(current_user.id),
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        logger.warning(f"[Chat] 对话不存在, conv_id={conversation_id}")
        raise NotFoundException("Conversation not found")
    logger.info(f"[Chat] 对话验证通过, conv_id={conversation_id}, title={conv.title}")

    # Parse attachments if provided
    all_attachments: list[tuple[str, str]] = []  # [(filename, parsed_content), ...]
    attachment_used = False

    parser = InstantFileParser()
    for file in valid_files:
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in ALLOWED_ATTACHMENT_TYPES:
            raise ValidationException(
                f"不支持的文件格式: .{ext}，支持: {', '.join(sorted(ALLOWED_ATTACHMENT_TYPES))}"
            )

        content = await file.read()
        if len(content) > settings.max_attachment_size:
            raise ValidationException(
                f"文件过大: {file.filename} ({len(content)} 字节)，最大允许 {settings.max_attachment_size} 字节"
            )

        # Parse file content synchronously
        try:
            async with ATTACHMENT_PARSE_SEMAPHORE:
                parsed = await asyncio.to_thread(parser.parse, file.filename, content)
            all_attachments.append((file.filename, parsed))
            logger.info(f"[Chat] 附件解析完成, filename={file.filename}, text_len={len(parsed)}")
        except ValidationException:
            raise
        except Exception as e:
            logger.error(f"[Chat] 附件解析失败: {e}", exc_info=True)
            raise ValidationException(f"附件解析失败 ({file.filename}): {e}")

        # Upload original file to MinIO
        try:
            await _save_attachment_to_minio(
                current_user.tenant_id,
                conversation_id,
                file.filename,
                content,
            )
        except Exception as e:
            logger.warning(f"[Chat] 附件上传MinIO失败(非致命): {e}")

    requested_kb_id = uuid.UUID(knowledge_base_id_str) if knowledge_base_id_str else None
    initial_active_kb_id = requested_kb_id or conv.knowledge_base_id
    if requested_kb_id:
        await require_visible_kb(db, current_user, requested_kb_id)
    elif initial_active_kb_id:
        result = await db.execute(
            visible_knowledge_base_query(current_user).where(
                KnowledgeBase.id == initial_active_kb_id
            )
        )
        if not result.scalar_one_or_none():
            initial_active_kb_id = None
    logger.info(f"[Chat] kb_id={initial_active_kb_id}")

    # Get history messages
    history_query = (
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at)
        .limit(20)
    )
    result = await db.execute(history_query)
    history_messages = result.scalars().all()
    logger.info(f"[Chat] 历史消息数量: {len(history_messages)}")

    # Build user message (with attachment injection)
    if all_attachments:
        blocks = []
        for fname, fcontent in all_attachments:
            blocks.append(f"[用户上传附件]\n文件名：{fname}\n内容：\n{fcontent}\n---")
        user_message_text = "\n\n".join(blocks) + "\n\n" + message
        attachment_used = True
    else:
        user_message_text = message

    # Save user message to DB (original message, not with attachment prefix)
    logger.info(f"[Chat] 保存用户消息")
    user_message = Message(
        conversation_id=conv.id,
        role="user",
        content=message,
    )
    db.add(user_message)
    await db.commit()
    await db.refresh(user_message)
    logger.info(f"[Chat] 用户消息已保存, msg_id={user_message.id}")

    # === 联网搜索状态管理 ===
    conv_meta = dict(conv.meta or {})
    web_search_mode = conv_meta.get("web_search_mode", "off")

    # Frontend toggle button takes priority
    if web_search is not None:
        web_search_mode = "on" if web_search else "off"
        conv_meta["web_search_mode"] = web_search_mode
        conv_meta.pop("ask_pending", None)
        conv_meta.pop("pending_ask_query", None)
        conv.meta = conv_meta
        db.add(conv)
        await db.commit()

    # Explicit keyword detection: user says "允许联网搜索" / "联网搜索" in message
    EXPLICIT_SEARCH_KEYWORDS = ("允许联网", "联网搜索", "外部搜索", "网上搜索", "公开信息")
    if web_search_mode != "on" and any(kw in message for kw in EXPLICIT_SEARCH_KEYWORDS):
        web_search_mode = "on"
        conv_meta["web_search_mode"] = "on"
        conv_meta.pop("ask_pending", None)
        conv_meta.pop("pending_ask_query", None)
        conv.meta = conv_meta
        db.add(conv)
        await db.commit()
        logger.info(f"[WebSearch] 用户消息含显式关键词，开启联网搜索")

    # Ask-pending: user replied to "是否允许联网搜索"
    if web_search_mode == "ask_pending":
        is_yes = _classify_yes_no(message)
        if is_yes:
            conv_meta["web_search_mode"] = "on"
            conv_meta.pop("ask_pending", None)
            conv_meta.pop("pending_ask_query", None)
            conv.meta = conv_meta
            db.add(conv)
            await db.commit()
            confirm_text = "好的，已开启联网搜索，请重新提问。"
            assist_msg = Message(conversation_id=conv.id, role="assistant", content=confirm_text, context={"web_search_mode": "on"})
            db.add(assist_msg)
            await db.commit()
            async def _yes_gen():
                yield f"data: {ChatStreamChunk(content=confirm_text, citations=[], finished=False, attachment_used=False).model_dump_json()}\n\n"
                yield f"data: {ChatStreamChunk(content='', citations=[], finished=True, attachment_used=False, web_search_mode='on').model_dump_json()}\n\n"
            return StreamingResponse(_yes_gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
        else:
            conv_meta["web_search_mode"] = "off"
            conv_meta.pop("ask_pending", None)
            conv_meta.pop("pending_ask_query", None)
            conv.meta = conv_meta
            db.add(conv)
            await db.commit()
            decline_text = "好的，如有需要随时让我开启联网搜索。"
            assist_msg = Message(conversation_id=conv.id, role="assistant", content=decline_text)
            db.add(assist_msg)
            await db.commit()
            async def _no_gen():
                yield f"data: {ChatStreamChunk(content=decline_text, citations=[], finished=False, attachment_used=False).model_dump_json()}\n\n"
                yield f"data: {ChatStreamChunk(content='', citations=[], finished=True, attachment_used=False, web_search_mode='off').model_dump_json()}\n\n"
            return StreamingResponse(_no_gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    async def generate_response():
        async with CHAT_PIPELINE_SEMAPHORE:
            t_total = time.time()
            full_content = ""
            citations_list = []
            artifacts: list[dict] = []
            timings: dict[str, int] = {}

            from core.llm.client import LLMClient

            t0 = time.time()
            kb_result = await db.execute(
                visible_knowledge_base_query(current_user)
            )
            all_kbs = kb_result.scalars().all()
            active_kb_name = next(
                (kb.name for kb in all_kbs if initial_active_kb_id and kb.id == initial_active_kb_id),
                "知识库",
            )
            timings["visible_kb_ms"] = int((time.time() - t0) * 1000)
            logger.info(f"[Timing] 查询知识库列表: {timings['visible_kb_ms']}ms, count={len(all_kbs)}")

            active_kb_id = initial_active_kb_id
            t0 = time.time()
            router_llm = None
            if settings.llm_classify_model or settings.llm_classify_base_url:
                router_llm = LLMClient(
                    api_key=settings.llm_classify_api_key or settings.llm_api_key,
                    base_url=settings.llm_classify_base_url or settings.llm_base_url,
                    model=settings.llm_classify_model or settings.llm_model,
                )
            router = RequestRouter(router_llm)
            orchestrator = AgentOrchestrator(router)
            agent_run_state, agent_plan = await orchestrator.start_run(
                query=message,
                has_attachments=bool(all_attachments),
                has_active_kb=bool(active_kb_id),
            )
            route_decision = agent_run_state.route_decision
            if route_decision is None:
                route_decision = await router.decide(
                    query=message,
                    has_attachments=bool(all_attachments),
                    has_active_kb=bool(active_kb_id),
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
            agent_run_db_id: uuid.UUID | None = None
            agent_step_db_id: uuid.UUID | None = None
            agent_finalize_step_db_id: uuid.UUID | None = None
            try:
                run_row = AgentRun(
                    tenant_id=uuid.UUID(current_user.tenant_id),
                    user_id=uuid.UUID(current_user.id),
                    conversation_id=conv.id,
                    goal=agent_run_state.goal,
                    status=agent_run_state.status,
                    route=route_decision.route,
                    current_step=agent_run_state.current_step,
                    next_step=agent_run_state.next_step,
                    completed_steps_summary=agent_run_state.completed_steps_summary,
                    plan_snapshot=agent_run_state.plan_snapshot,
                    step_history=agent_run_state.step_history,
                    artifacts=agent_run_state.artifacts,
                    last_error=agent_run_state.last_error or None,
                    retry_count=agent_run_state.retry_count,
                    budget_remaining=agent_run_state.budget_remaining,
                )
                db.add(run_row)
                await db.flush()
                agent_run_db_id = run_row.id

                step_row = AgentStep(
                    run_id=run_row.id,
                    step_key=agent_step_state.step_id,
                    step_type=agent_step_state.step_type,
                    step_goal=agent_step_state.step_goal,
                    status=agent_step_state.status,
                    output=agent_step_state.output,
                    error=agent_step_state.error,
                    tool_trace=agent_step_state.tool_trace,
                )
                db.add(step_row)
                await db.flush()
                agent_step_db_id = step_row.id
                await db.commit()
            except Exception as e:
                logger.warning(f"[Agent] 持久化初始化状态失败(非致命): {e}")
                await db.rollback()
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

            chunks_data = []
            retrieval_ms = 0
            timings["embedding_ms"] = 0
            timings["retrieval_ms"] = 0
            if active_kb_id and route_decision.route in {"rag_qa", "content_generation", "ppt_generation", "pdf_generation", "document_summary"}:
                try:
                    t0 = time.time()
                    logger.info(f"[Timing] 开始向量化, query={message[:30]}...")
                    embedding = EmbeddingClient()
                    query_vector = await embedding.embed_single(message)
                    timings["embedding_ms"] = int((time.time() - t0) * 1000)
                    logger.info(f"[Timing] 向量化完成: {timings['embedding_ms']}ms, dim={len(query_vector)}")

                    t0 = time.time()
                    retriever = Retriever(db)
                    retrieved, retrieval_timings = await retriever.similarity_search(
                        query_vector, str(active_kb_id),
                        top_k=5, threshold=0.2,
                        query_text=message,
                        use_rerank=True,
                        return_timings=True,
                    )
                    retrieval_ms = int((time.time() - t0) * 1000)
                    timings["retrieval_ms"] = retrieval_ms
                    timings["retrieval_vector_sql_ms"] = retrieval_timings.get("vector_sql_ms", 0)
                    timings["retrieval_bm25_ms"] = retrieval_timings.get("bm25_ms", 0)
                    timings["retrieval_rrf_ms"] = retrieval_timings.get("rrf_ms", 0)
                    timings["retrieval_rerank_ms"] = retrieval_timings.get("rerank_ms", 0)
                    timings["retrieval_total_ms"] = retrieval_timings.get("retrieval_total_ms", 0)
                    timings["retrieval_rerank_decision"] = retrieval_timings.get("rerank_decision", "off")
                    timings["retrieval_rerank_reason"] = retrieval_timings.get("rerank_reason", "")
                    timings["retrieval_rerank_candidate_k"] = retrieval_timings.get("rerank_candidate_k", 0)
                    timings["retrieval_rerank_cache_hit"] = retrieval_timings.get("rerank_cache_hit", False)
                    timings["retrieval_rerank_error"] = retrieval_timings.get("rerank_error", "")
                    logger.info(
                        f"[Timing] 混合检索完成: {retrieval_ms}ms, 返回{len(retrieved)}条, "
                        f"detail={retrieval_timings}"
                    )

                    for c in retrieved:
                        citations_list.append({
                            "chunk_id": c.chunk_id,
                            "document_title": c.document_title,
                            "score": c.score,
                        })
                        chunks_data.append({
                            "content": c.content,
                            "source": c.metadata.get("source") or f"知识库-{c.document_title}",
                            "chunk_type": c.metadata.get("chunk_strategy", "paragraph"),
                        })
                except Exception as e:
                    logger.warning(f"[Timing] RAG检索失败: {e}, 耗时={(time.time()-t0)*1000:.0f}ms")

            if active_kb_id:
                logger.info(f"[Timing] kb_id={str(active_kb_id)[:8]}..., chunks={len(chunks_data)}")

            # === KB miss handling: update web_search_mode ===
            nonlocal web_search_mode
            if active_kb_id and not chunks_data and not all_attachments:
                if web_search_mode == "off":
                    miss_count = conv_meta.get("kb_miss_count", 0) + 1
                    if miss_count >= 3:
                        web_search_mode = "on"
                        conv_meta["web_search_mode"] = "on"
                        conv_meta["kb_miss_count"] = 0
                        conv_meta.pop("ask_pending", None)
                        conv_meta.pop("pending_ask_query", None)
                        conv.meta = conv_meta
                        db.add(conv)
                        await db.commit()
                        logger.info(f"[WebSearch] 连续{miss_count}次KB miss, 自动开启联网搜索")
                    else:
                        web_search_mode = "ask_pending"
                        conv_meta["web_search_mode"] = "ask_pending"
                        conv_meta["kb_miss_count"] = miss_count
                        conv_meta["pending_ask_query"] = message
                        conv.meta = conv_meta
                        db.add(conv)
                        await db.commit()
                        logger.info(f"[WebSearch] KB miss #{miss_count}, 设置 ask_pending")
            elif active_kb_id and chunks_data:
                if conv_meta.get("kb_miss_count", 0) > 0:
                    conv_meta["kb_miss_count"] = 0
                    conv.meta = conv_meta
                    db.add(conv)
                    await db.commit()

            chat_model = settings.llm_chat_model or settings.llm_model
            llm = LLMClient(
                api_key=settings.llm_chat_api_key or settings.llm_api_key,
                base_url=settings.llm_chat_base_url or settings.llm_base_url,
                model=chat_model,
                timeout=90.0,
                api_header_name=settings.llm_chat_api_header_name,
                api_header_prefix=settings.llm_chat_api_header_prefix,
            )

            material_parts = []
            t_context = time.time()
            if all_attachments:
                for fname, fcontent in all_attachments:
                    material_parts.append(f"[用户上传附件:{fname}]\n{fcontent[:4000]}")
            if chunks_data:
                material_parts.append(_build_context_from_chunks(chunks_data))
            material_text = "\n\n".join(material_parts)
            source_hint = _infer_primary_source_label(chunks_data, bool(all_attachments))
            autonomous_tool_mode = _should_use_autonomous_tool_mode(
                route=route_decision.route,
                has_attachments=bool(all_attachments),
                allow_external_search=(task_profile.allow_external_search or web_search_mode == "on"),
            )
            available_tools = ["knowledge_retrieval", "solution_generator", "ppt_generation", "pdf_export"]
            if autonomous_tool_mode and (task_profile.allow_external_search or web_search_mode == "on"):
                available_tools.insert(1, "web_search")
            timings["context_build_ms"] = int((time.time() - t_context) * 1000)
            logger.info(
                f"[Timing] 上下文构建完成: attachments={len(all_attachments)}, "
                f"chunks={len(chunks_data)}, material_len={len(material_text)}, "
                f"source_hint={source_hint}, has_material={bool(material_parts)}"
            )

            try:
                if "[FORCE_AGENT_STEP1_FAIL]" in (message or ""):
                    raise RuntimeError("forced_step1_failure_for_mvp_regression")
                if autonomous_tool_mode:
                    registry = ToolRegistry()
                    if active_kb_id:
                        registry.register(
                            KnowledgeRetrievalTool(
                                kb_id=str(active_kb_id),
                                kb_name=active_kb_name,
                            )
                        )
                    if task_profile.allow_external_search or web_search_mode == "on":
                        registry.register(WebSearchTool())
                    registry.register(SolutionGeneratorTool(llm))
                    registry.register(PPTGenerationTool(tenant_id=current_user.tenant_id))
                    registry.register(PDFExportTool(tenant_id=current_user.tenant_id))

                    if web_search_mode == "on" or task_profile.allow_external_search:
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
                            yield f"data: {ChatStreamChunk(content=chunk, citations=[], finished=False, attachment_used=attachment_used).model_dump_json()}\n\n"
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
                                title=conv.title or "培训方案",
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
                        chunk_data = {
                            "content": "",
                            "citations": [],
                            "finished": False,
                            "attachment_used": attachment_used,
                            "artifact": artifact,
                            "ppt_task_id": artifact["task_id"] if artifact["type"] == "ppt" else None,
                            "pdf_task_id": artifact["task_id"] if artifact["type"] == "pdf" else None,
                        }
                        yield f"data: {ChatStreamChunk(**chunk_data).model_dump_json()}\n\n"
                elif route_decision.route == "ppt_generation":
                    prompt = build_ppt_generation_prompt(material_text or message, source_hint)
                    step_prompt = build_step_execution_prompt(
                        base_system_prompt=prompt,
                        goal=agent_run_state.goal,
                        plan_snapshot=agent_run_state.plan_snapshot,
                        current_step=agent_run_state.current_step or "step-1",
                        next_step=agent_run_state.next_step,
                        completed_steps_summary=agent_run_state.completed_steps_summary,
                        available_tools=available_tools,
                    )
                    ppt_messages = [{"role": "system", "content": step_prompt}]
                    for msg in history_messages[-6:]:
                        ppt_messages.append({"role": msg.role, "content": msg.content})
                    ppt_messages.append({"role": "user", "content": message})

                    t0 = time.time()
                    logger.info(f"[Timing] PPT链路调用LLM开始, model={chat_model}, messages={len(ppt_messages)}")
                    async for chunk in _stream_llm_response(llm, ppt_messages, temperature=0.2):
                        if "llm_first_token_ms" not in timings:
                            timings["llm_first_token_ms"] = int((time.time() - t0) * 1000)
                        full_content += chunk
                    timings["llm_total_ms"] = int((time.time() - t0) * 1000)
                    logger.info(f"[Timing] PPT链路LLM完成: {timings['llm_total_ms']}ms, chars={len(full_content)}")

                    ppt_tool = PPTGenerationTool(tenant_id=current_user.tenant_id)
                    task_payload = json.loads(
                        ppt_tool.invoke(content=full_content, title=conv.title or "培训方案")
                    )
                    if task_payload.get("task_id"):
                        artifact = {"type": "ppt", "task_id": task_payload["task_id"]}
                        artifacts.append(artifact)
                    summary_text = task_payload.get("message") or "PPT 生成任务已提交。"
                    if source_hint:
                        summary_text += f"\n来源：{source_hint}"
                    full_content = summary_text
                    yield f"data: {ChatStreamChunk(content=full_content, citations=citations_list, finished=False, attachment_used=attachment_used).model_dump_json()}\n\n"
                    for artifact in artifacts:
                        chunk_data = {
                            "content": "",
                            "citations": [],
                            "finished": False,
                            "attachment_used": attachment_used,
                            "artifact": artifact,
                            "ppt_task_id": artifact["task_id"] if artifact["type"] == "ppt" else None,
                        }
                        yield f"data: {ChatStreamChunk(**chunk_data).model_dump_json()}\n\n"
                elif route_decision.route == "pdf_generation":
                    prompt = build_pdf_generation_prompt(material_text or message, source_hint)
                    step_prompt = build_step_execution_prompt(
                        base_system_prompt=prompt,
                        goal=agent_run_state.goal,
                        plan_snapshot=agent_run_state.plan_snapshot,
                        current_step=agent_run_state.current_step or "step-1",
                        next_step=agent_run_state.next_step,
                        completed_steps_summary=agent_run_state.completed_steps_summary,
                        available_tools=available_tools,
                    )
                    pdf_messages = [{"role": "system", "content": step_prompt}]
                    for msg in history_messages[-6:]:
                        pdf_messages.append({"role": msg.role, "content": msg.content})
                    pdf_messages.append({"role": "user", "content": message})

                    t0 = time.time()
                    logger.info(f"[Timing] PDF链路调用LLM开始, model={chat_model}, messages={len(pdf_messages)}")
                    async for chunk in _stream_llm_response(llm, pdf_messages, temperature=0.2):
                        if "llm_first_token_ms" not in timings:
                            timings["llm_first_token_ms"] = int((time.time() - t0) * 1000)
                        full_content += chunk
                    timings["llm_total_ms"] = int((time.time() - t0) * 1000)
                    logger.info(f"[Timing] PDF链路LLM完成: {timings['llm_total_ms']}ms, chars={len(full_content)}")

                    pdf_tool = PDFExportTool(tenant_id=current_user.tenant_id)
                    task_payload = json.loads(
                        pdf_tool.invoke(content=full_content, title=conv.title or "培训方案")
                    )
                    if task_payload.get("task_id"):
                        artifact = {"type": "pdf", "task_id": task_payload["task_id"]}
                        artifacts.append(artifact)
                    summary_text = task_payload.get("message") or "PDF 生成任务已提交。"
                    if source_hint:
                        summary_text += f"\n来源：{source_hint}"
                    full_content = summary_text
                    yield f"data: {ChatStreamChunk(content=full_content, citations=citations_list, finished=False, attachment_used=attachment_used).model_dump_json()}\n\n"
                    for artifact in artifacts:
                        chunk_data = {
                            "content": "",
                            "citations": [],
                            "finished": False,
                            "attachment_used": attachment_used,
                            "artifact": artifact,
                            "pdf_task_id": artifact["task_id"] if artifact["type"] == "pdf" else None,
                        }
                        yield f"data: {ChatStreamChunk(**chunk_data).model_dump_json()}\n\n"
                else:
                    if route_decision.route == "document_summary":
                        system_prompt = build_document_summary_prompt(material_text or user_message_text, source_hint)
                    elif route_decision.route == "content_generation":
                        system_prompt = build_content_generation_prompt(material_text or user_message_text, source_hint)
                    elif route_decision.route == "rag_qa":
                        if all_attachments and chunks_data:
                            system_prompt = build_attachment_with_kb_prompt(_build_context_from_chunks(chunks_data), source_type="local")
                        elif all_attachments:
                            system_prompt = build_attachment_only_prompt(source_type="local")
                        elif chunks_data:
                            system_prompt = build_kb_only_prompt(_build_context_from_chunks(chunks_data))
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
                    async for chunk in _stream_llm_response(llm, llm_messages, temperature=0.1):
                        if chunk:
                            if first_chunk_time is None:
                                first_chunk_time = time.time()
                                timings["llm_first_token_ms"] = int((first_chunk_time - t0) * 1000)
                                logger.info(f"[Timing] LLM首token: {timings['llm_first_token_ms']}ms")
                            full_content += chunk
                            yield f"data: {ChatStreamChunk(content=chunk, citations=[], finished=False, attachment_used=attachment_used).model_dump_json()}\n\n"
                    timings["llm_total_ms"] = int((time.time() - t0) * 1000)
                    logger.info(f"[Timing] LLM响应完成: {timings['llm_total_ms']}ms, chars={len(full_content)}")
                    # Ask-pending: append gentle ask to response
                    if web_search_mode == "ask_pending":
                        ask_text = '\n\n---\n知识库暂无相关信息，是否允许我开启联网搜索？（回复"好的"开启，或说"不用了"）'
                        full_content += ask_text
                        yield f"data: {ChatStreamChunk(content=ask_text, citations=[], finished=False, attachment_used=attachment_used).model_dump_json()}\n\n"
            except Exception as e:
                logger.error(f"[Timing] LLM调用失败: {e}", exc_info=True)
                err_msg = str(e)
                err_type = orchestrator.policy.classify_error(err_msg)
                fallback = orchestrator.policy.fallback_message_for(err_type)
                yield f"data: {ChatStreamChunk(content=fallback, citations=[], finished=False, attachment_used=attachment_used).model_dump_json()}\n\n"
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
            if agent_run_db_id and agent_step_db_id:
                try:
                    await db.execute(
                        update(AgentStep)
                        .where(AgentStep.id == agent_step_db_id)
                        .values(
                            status=agent_step_state.status,
                            output=agent_step_state.output,
                            error=agent_step_state.error,
                            tool_trace=agent_step_state.tool_trace,
                        )
                    )
                    await db.execute(
                        update(AgentRun)
                        .where(AgentRun.id == agent_run_db_id)
                        .values(
                            status=agent_run_state.status,
                            current_step=agent_run_state.current_step,
                            next_step=agent_run_state.next_step,
                            completed_steps_summary=agent_run_state.completed_steps_summary,
                            step_history=agent_run_state.step_history,
                            artifacts=agent_run_state.artifacts,
                            last_error=agent_run_state.last_error or None,
                            retry_count=agent_run_state.retry_count,
                            budget_remaining=agent_run_state.budget_remaining,
                            completed_at=datetime.utcnow() if agent_run_state.status in {"completed", "failed", "stopped"} else None,
                        )
                    )
                    await db.commit()
                except Exception as e:
                    logger.warning(f"[Agent] 持久化结束状态失败(非致命): {e}")
                    await db.rollback()

            # Dynamic follow-up step: finalize / retry-decision / fallback-finalize.
            followup_step_def = orchestrator.planner.build_followup_step(
                agent_run_state,
                agent_step_state,
                max_retries=orchestrator.policy.max_retries,
            )
            if followup_step_def:
                # Add follow-up step into snapshot for visibility/query API.
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
                            async for chunk in _stream_llm_response(llm, retry_messages, temperature=0.1):
                                if chunk:
                                    retry_output += chunk
                                    yield f"data: {ChatStreamChunk(content=chunk, citations=[], finished=False, attachment_used=attachment_used).model_dump_json()}\n\n"
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
                        if agent_step_db_id:
                            try:
                                await db.execute(
                                    update(AgentStep)
                                    .where(AgentStep.id == agent_step_db_id)
                                    .values(output=full_content)
                                )
                                await db.commit()
                            except Exception as e:
                                logger.warning(f"[Agent] 更新重试后主输出失败(非致命): {e}")
                                await db.rollback()
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
                if agent_run_db_id:
                    try:
                        if finalize_step_state is not None:
                            finalize_row = AgentStep(
                                run_id=agent_run_db_id,
                                step_key=finalize_step_state.step_id,
                                step_type=finalize_step_state.step_type,
                                step_goal=finalize_step_state.step_goal,
                                status=finalize_step_state.status,
                                output=finalize_step_state.output,
                                error=finalize_step_state.error,
                                tool_trace=finalize_step_state.tool_trace,
                            )
                            db.add(finalize_row)
                            await db.flush()
                            agent_finalize_step_db_id = finalize_row.id
                        await db.execute(
                            update(AgentRun)
                            .where(AgentRun.id == agent_run_db_id)
                            .values(
                                status=agent_run_state.status,
                                current_step=agent_run_state.current_step,
                                next_step=agent_run_state.next_step,
                                completed_steps_summary=agent_run_state.completed_steps_summary,
                                step_history=agent_run_state.step_history,
                                artifacts=agent_run_state.artifacts,
                                last_error=agent_run_state.last_error or None,
                                retry_count=agent_run_state.retry_count,
                                budget_remaining=agent_run_state.budget_remaining,
                                completed_at=datetime.utcnow() if agent_run_state.status in {"completed", "failed", "stopped"} else None,
                            )
                        )
                        await db.commit()
                    except Exception as e:
                        logger.warning(f"[Agent] 持久化finalize步骤失败(非致命): {e}")
                        await db.rollback()

            latency_ms = int((time.time() - t_total) * 1000)
            timings["total_ms"] = latency_ms
            logger.info(
                f"[Timing] 总耗时: {latency_ms}ms, "
                f"routing={route_decision.route}, retrieval_ms={retrieval_ms}, "
                f"attachments={len(all_attachments)}, citations={len(citations_list)}"
            )

            assistant_message = Message(
                conversation_id=conv.id,
                role="assistant",
                content=full_content,
                citations=citations_list,
                context={
                    "route": route_decision.route,
                    "decision_source": route_decision.decision_source,
                    "reason": route_decision.reason,
                    "confidence": route_decision.confidence,
                    "agent": {
                        "run_id": agent_run_state.run_id,
                        "run_db_id": str(agent_run_db_id) if agent_run_db_id else None,
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
            )
            db.add(assistant_message)
            await db.commit()

            yield f"data: {ChatStreamChunk(content='', citations=[], finished=False, attachment_used=attachment_used, agent={'run_id': agent_run_state.run_id, 'run_db_id': str(agent_run_db_id) if agent_run_db_id else None, 'status': agent_run_state.status, 'current_step': agent_run_state.current_step, 'next_step': agent_run_state.next_step, 'completed_steps_summary': agent_run_state.completed_steps_summary}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamChunk(content='', citations=[], finished=True, attachment_used=attachment_used, web_search_mode=web_search_mode).model_dump_json()}\n\n"

    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/conversations/{conversation_id}/chat")
async def chat_json(
    conversation_id: str,
    data: ChatRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    """Chat endpoint (JSON body, backward compatible, no file)."""
    return await _handle_chat(
        conversation_id=conversation_id,
        message=data.message,
        knowledge_base_id_str=data.knowledge_base_id,
        web_search=data.web_search,
        files=[],
        db=db,
        current_user=current_user,
    )


@router.post("/conversations/{conversation_id}/chat/upload")
async def chat_with_attachment(
    conversation_id: str,
    db: DBSession,
    current_user: CurrentUser,
    message: str = Form(...),
    knowledge_base_id: Optional[str] = Form(None),
    web_search: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[]),
):
    """Chat endpoint with file attachments (multipart/form-data)."""
    try:
        return await _handle_chat(
            conversation_id=conversation_id,
            message=message,
            knowledge_base_id_str=knowledge_base_id,
            web_search=(web_search == "true") if web_search is not None else None,
            files=files,
            db=db,
            current_user=current_user,
        )
    except NotFoundException as e:
        return JSONResponse(status_code=404, content={"code": 404, "data": None, "msg": e.message})
    except ValidationException as e:
        return JSONResponse(status_code=400, content={"code": 400, "data": None, "msg": e.message})
    except Exception as e:
        logger.error(f"[Chat] 端点异常: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"code": 500, "data": None, "msg": str(e)})
