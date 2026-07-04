"""Conversation and message CRUD operations."""

import uuid
import logging
from typing import Optional

from sqlalchemy import select, func

from api.schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    ConversationListResponse,
    MessageResponse,
)
from core.exceptions import NotFoundException
from models.tables import Conversation, Message

logger = logging.getLogger(__name__)


async def list_conversations(db, current_user, page: int = 1, page_size: int = 20):
    """List conversations for the current user."""
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
    return items


async def create_conversation(data: ConversationCreate, db, current_user):
    """Create a new conversation."""
    kb_id = uuid.UUID(data.knowledge_base_id) if data.knowledge_base_id else None

    conv = Conversation(
        tenant_id=uuid.UUID(current_user.tenant_id),
        user_id=uuid.UUID(current_user.id),
        knowledge_base_id=kb_id,
        title=data.title,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return ConversationResponse(
        id=str(conv.id),
        tenant_id=str(conv.tenant_id),
        user_id=str(conv.user_id),
        knowledge_base_id=str(conv.knowledge_base_id) if conv.knowledge_base_id else None,
        title=conv.title,
        message_count=0,
        created_at=conv.created_at,
    )


async def get_conversation_messages(conversation_id: str, db, current_user):
    """Get all messages in a conversation."""
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

    return [
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


async def validate_conversation(conversation_id: str, db, current_user):
    """Validate that a conversation exists and belongs to the current user.

    Returns the Conversation ORM object.
    """
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
    return conv


async def save_user_message(conversation_id: uuid.UUID, content: str, db) -> Message:
    """Save a user message to DB."""
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=content,
    )
    db.add(user_message)
    await db.commit()
    await db.refresh(user_message)
    logger.info(f"[Chat] 用户消息已保存, msg_id={user_message.id}")
    return user_message


async def save_assistant_message(
    conversation_id: uuid.UUID,
    content: str,
    citations: list,
    context: dict,
    token_count: int,
    latency_ms: int,
    db,
) -> Message:
    """Save an assistant message to DB."""
    assistant_message = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=content,
        citations=citations,
        context=context,
        token_count=token_count,
        latency_ms=latency_ms,
    )
    db.add(assistant_message)
    await db.commit()
    return assistant_message


async def get_history_messages(conversation_id: uuid.UUID, db, limit: int = 20):
    """Get recent history messages for a conversation."""
    history_query = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .limit(limit)
    )
    result = await db.execute(history_query)
    history_messages = result.scalars().all()
    logger.info(f"[Chat] 历史消息数量: {len(history_messages)}")
    return history_messages
