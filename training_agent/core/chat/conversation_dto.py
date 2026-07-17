"""Conversation and message DTOs.

Moved from api/schemas/chat.py to eliminate core->api reverse dependency.
api/schemas/chat.py re-exports these for backward compatibility.
"""
from __future__ import annotations

from datetime import datetime

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
    knowledge_base_id: str | None = None


class ConversationResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    knowledge_base_id: str | None = None
    title: str
    message_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    id: str
    title: str
    knowledge_base_id: str | None = None
    message_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}
