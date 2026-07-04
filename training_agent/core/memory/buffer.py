"""Conversation Memory.

Conversation memory management.
"""

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.tables import Message


class ConversationMemory:
    """Conversation memory manager."""

    def __init__(self, conversation_id: str, db: Optional[AsyncSession] = None):
        """Initialize memory.

        Args:
            conversation_id: Conversation ID
            db: Database session
        """
        self.conversation_id = uuid.UUID(conversation_id) if isinstance(conversation_id, str) else conversation_id
        self._db = db

    async def get_history(
        self,
        limit: int = 10,
    ) -> list[dict]:
        """Get conversation history.

        Args:
            limit: Number of messages

        Returns:
            List of message dicts
        """
        if not self._db:
            return []

        query = (
            select(Message)
            .where(Message.conversation_id == self.conversation_id)
            .order_by(Message.created_at)
            .limit(limit)
        )

        result = await self._db.execute(query)
        messages = result.scalars().all()

        return [
            {
                "role": msg.role,
                "content": msg.content,
            }
            for msg in messages
        ]

    async def add_message(
        self,
        role: str,
        content: str,
        context: Optional[dict] = None,
        citations: Optional[list] = None,
        token_count: int = 0,
        latency_ms: int = 0,
    ) -> Message:
        """Add message to history.

        Args:
            role: Message role (user/assistant)
            content: Message content
            context: Optional context
            citations: Optional citations
            token_count: Token count
            latency_ms: Latency in ms

        Returns:
            Created message
        """
        if not self._db:
            raise RuntimeError("Database session not available")

        message = Message(
            conversation_id=self.conversation_id,
            role=role,
            content=content,
            context=context or {},
            citations=citations or [],
            token_count=token_count,
            latency_ms=latency_ms,
        )

        self._db.add(message)
        await self._db.commit()
        await self._db.refresh(message)

        return message

    async def get_messages_for_context(
        self,
        limit: int = 5,
    ) -> list[dict]:
        """Get recent messages for LLM context.

        Args:
            limit: Number of messages

        Returns:
            List of message dicts
        """
        if not self._db:
            return []

        query = (
            select(Message)
            .where(Message.conversation_id == self.conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )

        result = await self._db.execute(query)
        messages = list(result.scalars().all())

        messages.reverse()

        return [
            {
                "role": msg.role,
                "content": msg.content,
            }
            for msg in messages
        ]

    async def count(self) -> int:
        """Count messages.

        Returns:
            Message count
        """
        if not self._db:
            return 0

        from sqlalchemy import func

        query = (
            select(func.count(Message.id))
            .where(Message.conversation_id == self.conversation_id)
        )

        result = await self._db.execute(query)
        return result.scalar() or 0


class SyncConversationMemory:
    """Synchronous conversation memory."""

    def __init__(self, conversation_id: str):
        """Initialize memory.

        Args:
            conversation_id: Conversation ID
        """
        self.conversation_id = uuid.UUID(conversation_id) if isinstance(conversation_id, str) else conversation_id

    def get_history(self, limit: int = 10) -> list[dict]:
        """Get conversation history synchronously.

        Args:
            limit: Number of messages

        Returns:
            List of message dicts
        """
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from core.config import settings

        engine = create_engine(settings.sync_database_url)

        with Session(engine) as db:
            query = (
                select(Message)
                .where(Message.conversation_id == self.conversation_id)
                .order_by(Message.created_at)
                .limit(limit)
            )

            result = db.execute(query)
            messages = result.scalars().all()

            return [
                {
                    "role": msg.role,
                    "content": msg.content,
                }
                for msg in messages
            ]