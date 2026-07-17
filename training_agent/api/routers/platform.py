import uuid
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from api.deps import DBSession
from api.schemas.common import Response
from api.schemas.platform import PlatformCallbackResponse
from core.adapters.base import PlatformMessage
from core.adapters.registry import get_adapter
from core.config import settings
from core.llm.factory import get_llm_client
from core.prompts.chat import build_kb_only_prompt
from core.prompts.platform import get_platform_prompt
from core.rag.retriever import Retriever
from core.services.platform_user import PlatformUserService
from models.tables import Conversation, KnowledgeBase, Message, PlatformConversation, PlatformMessageReceipt, User

logger = logging.getLogger(__name__)

router = APIRouter()
platform_user_service = PlatformUserService()


async def _get_or_create_conversation(
    db: DBSession,
    user: User,
    platform: str,
    platform_conversation_id: str,
) -> Conversation:
    mapping_res = await db.execute(
        select(PlatformConversation).where(
            PlatformConversation.platform == platform,
            PlatformConversation.platform_conversation_id == platform_conversation_id,
        )
    )
    mapping = mapping_res.scalar_one_or_none()
    if mapping:
        conv_res = await db.execute(select(Conversation).where(Conversation.id == mapping.conversation_id))
        conv = conv_res.scalar_one_or_none()
        if conv:
            return conv

    kb_res = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.tenant_id == user.tenant_id)
        .order_by(KnowledgeBase.created_at.asc())
        .limit(1)
    )
    kb = kb_res.scalar_one_or_none()
    conv = Conversation(
        tenant_id=user.tenant_id,
        user_id=user.id,
        knowledge_base_id=kb.id if kb else None,
        title=f"{platform}:{platform_conversation_id[:32]}",
    )
    db.add(conv)
    await db.flush()

    new_mapping = PlatformConversation(
        tenant_id=user.tenant_id,
        user_id=user.id,
        conversation_id=conv.id,
        platform=platform,
        platform_conversation_id=platform_conversation_id,
    )
    db.add(new_mapping)
    await db.commit()
    await db.refresh(conv)
    return conv


async def _already_processed(
    db: DBSession,
    user: User,
    platform: str,
    platform_message_id: str,
) -> bool:
    if not platform_message_id:
        return False
    res = await db.execute(
        select(PlatformMessageReceipt).where(
            PlatformMessageReceipt.platform == platform,
            PlatformMessageReceipt.platform_message_id == platform_message_id,
        )
    )
    existing = res.scalar_one_or_none()
    return existing is not None


async def _mark_processed(
    db: DBSession,
    user: User,
    platform: str,
    platform_message_id: str,
    conversation_id: uuid.UUID,
) -> None:
    if not platform_message_id:
        return
    db.add(
        PlatformMessageReceipt(
            tenant_id=user.tenant_id,
            user_id=user.id,
            platform=platform,
            platform_message_id=platform_message_id,
            conversation_id=conversation_id,
        )
    )
    await db.commit()


async def _build_assistant_answer(
    db: DBSession,
    conv: Conversation,
    incoming: PlatformMessage,
    platform: str,
) -> tuple[str, list[dict]]:
    history_res = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(10)
    )
    history = list(reversed(history_res.scalars().all()))

    citations: list[dict] = []
    context_prompt = ""
    if conv.knowledge_base_id:
        try:
            chunks = await Retriever(db).search(
                incoming.content,
                str(conv.knowledge_base_id),
                top_k=5,
                threshold=0.2,
                use_rerank=True,
            )
            if chunks:
                parts = []
                for i, c in enumerate(chunks, 1):
                    source = c.metadata.get("source") or f"知识库-{c.document_title}"
                    parts.append(f"【{i}】[{source}]\n{c.content[:500]}")
                    citations.append({"chunk_id": c.chunk_id, "document_title": c.document_title, "score": c.score})
                context_prompt = build_kb_only_prompt("\n\n".join(parts))
        except Exception as e:
            logger.warning(f"[Platform] retrieval failed: {e}")

    system_prompt = get_platform_prompt(platform, "system")
    if context_prompt:
        system_prompt = f"{system_prompt}\n\n{context_prompt}"

    messages = [{"role": "system", "content": system_prompt}]
    for m in history:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": incoming.content})

    llm = get_llm_client("chat")
    answer = llm.chat(messages, stream=False, temperature=0.1)
    if not answer:
        answer = get_platform_prompt(platform, "fallback")
    return str(answer), citations


@router.post("/platform/{platform}/callback")
async def platform_callback(platform: str, request: Request, db: DBSession):
    adapter = get_adapter(platform)
    if not adapter:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {platform}")

    raw_data = await request.json()
    if raw_data.get("type") == "url_verification" and raw_data.get("challenge"):
        return {"challenge": raw_data["challenge"]}

    if not await adapter.verify_signature(request):
        raise HTTPException(status_code=401, detail="签名验证失败")

    message = await adapter.parse_message(raw_data)
    if not message.content:
        return Response(data=PlatformCallbackResponse(status="ignored_empty"))

    user_info = await adapter.get_user_info(message.user_id)
    user = await platform_user_service.get_or_create_user(
        db=db,
        platform=message.platform,
        platform_user_id=message.user_id,
        display_name=user_info.get("display_name") or message.user_id,
    )

    duplicated = await _already_processed(db, user, message.platform, message.platform_message_id)
    if duplicated:
        return Response(
            data=PlatformCallbackResponse(
                status="duplicated",
                message_id=message.platform_message_id,
                duplicated=True,
            )
        )

    conv = await _get_or_create_conversation(
        db=db,
        user=user,
        platform=message.platform,
        platform_conversation_id=message.conversation_id,
    )

    db.add(
        Message(
            conversation_id=conv.id,
            role="user",
            content=message.content,
        )
    )
    await db.commit()

    answer, citations = await _build_assistant_answer(db, conv, message, platform)
    db.add(
        Message(
            conversation_id=conv.id,
            role="assistant",
            content=answer,
            citations=citations,
            token_count=len(answer.split()),
        )
    )
    await db.commit()
    await _mark_processed(db, user, message.platform, message.platform_message_id, conv.id)

    await adapter.send_response(message.conversation_id, answer)
    return Response(
        data=PlatformCallbackResponse(
            status="success",
            conversation_id=str(conv.id),
            message_id=message.platform_message_id,
        )
    )
