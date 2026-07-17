from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    citations: list[dict] = []
    token_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    title: str = Field(default="New Conversation", max_length=500)
    knowledge_base_id: Optional[str] = None


class ConversationResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    knowledge_base_id: Optional[str] = None
    title: str
    message_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    id: str
    title: str
    knowledge_base_id: Optional[str] = None
    message_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    knowledge_base_id: Optional[str] = None
    web_search: Optional[bool] = None


class ChatResponse(BaseModel):
    message_id: str
    content: str
    citations: list[dict] = []
    token_count: int = 0
    latency_ms: int = 0


# ChatStreamChunk 已移至 core/chat/stream_types.py（消除 core→api 反向依赖）
# 此处 re-export 保持向后兼容
from core.chat.stream_types import ChatStreamChunk  # noqa: E402,F401
