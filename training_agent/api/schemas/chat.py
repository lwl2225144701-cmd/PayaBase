from datetime import datetime
from typing import Any, Optional

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


class ChatStreamChunk(BaseModel):
    content: str
    citations: list[dict] = []
    finished: bool = False
    attachment_used: bool = False
    ppt_task_id: Optional[str] = None  # deprecated, use artifact
    pdf_task_id: Optional[str] = None  # deprecated, use artifact
    artifact: Optional[dict] = None  # {"type": "ppt"|"pdf", "task_id": "..."}
    agent: Optional[dict] = None  # {"run_id": "...", "run_db_id": "...", ...}
    web_search_mode: Optional[str] = None  # "off" | "on" | "ask_pending"
