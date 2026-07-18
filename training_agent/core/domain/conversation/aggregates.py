"""Conversation 领域实体（Phase 4 充实）。

聚合根：Conversation（含 Message 内部实体）。此前会话可见性 / 归属判断散落在
router 与 chat_pipeline，本模块收拢为领域方法。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass
class Message:
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    token_count: int = 0
    latency_ms: int = 0
    context: dict = field(default_factory=dict)
    citations: list = field(default_factory=list)
    created_at: datetime | None = None

    def is_user(self) -> bool:
        return self.role == "user"

    def is_assistant(self) -> bool:
        return self.role == "assistant"

    @classmethod
    def from_orm(cls, orm) -> Message:
        return cls(
            id=orm.id,
            conversation_id=orm.conversation_id,
            role=orm.role,
            content=orm.content,
            token_count=orm.token_count or 0,
            latency_ms=orm.latency_ms or 0,
            context=orm.context or {},
            citations=orm.citations or [],
            created_at=orm.created_at,
        )


@dataclass
class Conversation:
    id: UUID
    tenant_id: UUID
    user_id: UUID
    title: str
    knowledge_base_id: UUID | None = None
    meta: dict = field(default_factory=dict)
    created_at: datetime | None = None

    def belongs_to_kb(self, kb_id: UUID) -> bool:
        return self.knowledge_base_id == kb_id

    @classmethod
    def from_orm(cls, orm) -> Conversation:
        return cls(
            id=orm.id,
            tenant_id=orm.tenant_id,
            user_id=orm.user_id,
            title=orm.title,
            knowledge_base_id=orm.knowledge_base_id,
            meta=orm.meta or {},
            created_at=orm.created_at,
        )
