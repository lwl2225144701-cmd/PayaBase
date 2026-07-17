"""Conversation / Message 仓储端口。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from models.tables import Conversation, Message


class ConversationRepository(Protocol):
    """会话聚合根仓储。"""

    async def get_by_id(
        self, conv_id: UUID, tenant_id: UUID, user_id: UUID
    ) -> Conversation | None:
        """按 ID + 租户 + 用户获取会话（可见性隔离）。"""
        ...

    async def list_by_user(
        self, tenant_id: UUID, user_id: UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[Conversation], int]:
        """分页列出用户会话，返回 (items, total)。"""
        ...

    async def save(self, conv: Conversation) -> Conversation:
        """新建或更新会话。"""
        ...

    async def delete(self, conv_id: UUID, tenant_id: UUID, user_id: UUID) -> bool:
        """删除会话（可见性校验），返回是否删除成功。"""
        ...


class MessageRepository(Protocol):
    """消息仓储（Conversation 聚合内部实体）。"""

    async def list_by_conversation(
        self, conv_id: UUID, limit: int = 20
    ) -> list[Message]:
        """按时间顺序读取会话最近消息。"""
        ...

    async def save(self, msg: Message) -> Message:
        """新建消息。"""
        ...
