"""Chat Service.

Provides business logic for conversation and chat operations.
"""

import uuid
from typing import Optional, AsyncGenerator

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.tables import Conversation, Message, KnowledgeBase, QueryLog
from core.exceptions import NotFoundException


class ChatService:
    """Service for conversation and chat operations."""

    def __init__(self, db: AsyncSession):
        """Initialize service.

        Args:
            db: Database session
        """
        self.db = db

    async def list_conversations(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Conversation], int]:
        """List conversations for a user.

        Args:
            tenant_id: Tenant ID
            user_id: User ID
            page: Page number
            page_size: Page size

        Returns:
            Tuple of (conversations, total count)
        """
        query = (
            select(Conversation)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.user_id == user_id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(query)
        conversations = result.scalars().all()

        count_query = select(func.count()).select_from(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.user_id == user_id,
        )
        total = await self.db.scalar(count_query) or 0

        return list(conversations), total

    async def get_conversation(
        self,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Optional[Conversation]:
        """Get conversation by ID.

        Args:
            conversation_id: Conversation ID
            user_id: User ID

        Returns:
            Conversation or None
        """
        result = await self.db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_conversation(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        title: str,
        knowledge_base_id: Optional[uuid.UUID] = None,
    ) -> Conversation:
        """Create new conversation.

        Args:
            tenant_id: Tenant ID
            user_id: User ID
            title: Conversation title
            knowledge_base_id: Optional knowledge base ID

        Returns:
            Created conversation
        """
        if knowledge_base_id:
            result = await self.db.execute(
                select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id)
            )
            if not result.scalar_one_or_none():
                raise NotFoundException("Knowledge base not found")

        conv = Conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
            title=title,
        )
        self.db.add(conv)
        await self.db.commit()
        await self.db.refresh(conv)
        return conv

    async def get_messages(
        self,
        conversation_id: uuid.UUID,
    ) -> list[Message]:
        """Get messages for a conversation.

        Args:
            conversation_id: Conversation ID

        Returns:
            List of messages
        """
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        return list(result.scalars().all())

    async def add_message(
        self,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        context: Optional[dict] = None,
        citations: Optional[list[dict]] = None,
        token_count: int = 0,
        latency_ms: int = 0,
    ) -> Message:
        """Add message to conversation.

        Args:
            conversation_id: Conversation ID
            role: Message role (user/assistant)
            content: Message content
            context: Optional context dict
            citations: Optional citations list
            token_count: Token count
            latency_ms: Latency in milliseconds

        Returns:
            Created message
        """
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            context=context or {},
            citations=citations or [],
            token_count=token_count,
            latency_ms=latency_ms,
        )
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def stream_chat(
        self,
        conversation_id: uuid.UUID,
        message: str,
    ) -> AsyncGenerator[str, None]:
        """Stream chat response.

        Args:
            conversation_id: Conversation ID
            message: User message

        Yields:
            Response chunks
        """
        full_content = ""
        citations = []

        # TODO: Implement RAG + LLM integration
        placeholder_chunks = [
            "Processing your query",
            "Retrieving relevant documents",
            "Generating response",
        ]

        for chunk_text in placeholder_chunks:
            full_content += chunk_text + ". "
            yield f'data: {{"content": "{chunk_text}. ", "citations": [], "finished": false}}\n\n'

        yield 'data: {"content": "", "citations": [], "finished": true}\n\n'

    async def log_query(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        query: str,
        answer: str,
        knowledge_base_id: Optional[uuid.UUID] = None,
        latency_ms: int = 0,
    ) -> QueryLog:
        """Log query for analytics.

        Args:
            tenant_id: Tenant ID
            user_id: User ID
            query: User query
            answer: Assistant answer
            knowledge_base_id: Optional knowledge base ID
            latency_ms: Latency in milliseconds

        Returns:
            Created query log
        """
        log = QueryLog(
            tenant_id=tenant_id,
            user_id=user_id,
            query=query,
            answer=answer,
            knowledge_base_id=knowledge_base_id,
            latency_ms=latency_ms,
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log