from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    knowledge_base_id: str | None = None
    web_search: bool | None = None


class ChatResponse(BaseModel):
    message_id: str
    content: str
    citations: list[dict] = []
    token_count: int = 0
    latency_ms: int = 0


# Conversation/message DTOs 已移至 core/chat/（消除 core->api 反向依赖）
# 此处 re-export 保持向后兼容
from core.chat.conversation_dto import (  # noqa: E402,F401,I001
    ConversationCreate,
    ConversationListResponse,
    ConversationResponse,
    MessageResponse,
)
# ChatStreamChunk 已移至 core/chat/stream_types.py（消除 core->api 反向依赖）
from core.chat.stream_types import ChatStreamChunk  # noqa: E402,F401,I001
