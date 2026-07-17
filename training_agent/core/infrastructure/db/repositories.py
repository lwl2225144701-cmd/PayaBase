"""领域仓储端口的 SQLAlchemy 异步实现。

设计要点：
- 只 add / flush / execute，不 commit / rollback（事务由 UnitOfWork 管）。
- 端口方法返回 ORM 模型对象（Phase 4 引入独立领域实体 + 映射后替换）。
- 租户隔离：写操作校验 tenant_id，读操作按 tenant_id 过滤。
- hybrid_search 留 Phase 3 从 retriever 迁移（涉及向量+BM25+RRF+rerank）。
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.tables import (
    AgentRun,
    AgentStep,
    Chunk,
    Conversation,
    Document,
    KnowledgeBase,
    Message,
)


class KnowledgeBaseRepositoryImpl:
    """KnowledgeBaseRepository 端口实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, kb_id: UUID, tenant_id: UUID) -> KnowledgeBase | None:
        result = await self.session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id,
                KnowledgeBase.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_tenant(
        self, tenant_id: UUID, department_id: UUID | None = None
    ) -> list[KnowledgeBase]:
        stmt = select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id)
        if department_id is not None:
            stmt = stmt.where(KnowledgeBase.department_id == department_id)
        stmt = stmt.order_by(KnowledgeBase.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def save(self, kb: KnowledgeBase) -> KnowledgeBase:
        self.session.add(kb)
        await self.session.flush()
        return kb

    async def delete(self, kb_id: UUID, tenant_id: UUID) -> bool:
        result = await self.session.execute(
            delete(KnowledgeBase)
            .where(KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == tenant_id)
            .execution_options(synchronize_session=False)
        )
        return (result.rowcount or 0) > 0


class DocumentRepositoryImpl:
    """DocumentRepository 端口实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, doc_id: UUID) -> Document | None:
        result = await self.session.execute(
            select(Document).where(Document.id == doc_id)
        )
        return result.scalar_one_or_none()

    async def list_by_kb(self, kb_id: UUID) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(Document.knowledge_base_id == kb_id)
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    async def save(self, doc: Document) -> Document:
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def update_status(self, doc_id: UUID, status: str, **fields: Any) -> None:
        values: dict[str, Any] = {"status": status, **fields}
        await self.session.execute(
            update(Document).where(Document.id == doc_id).values(**values)
        )

    async def delete(self, doc_id: UUID) -> bool:
        result = await self.session.execute(
            delete(Document).where(Document.id == doc_id).execution_options(synchronize_session=False)
        )
        return (result.rowcount or 0) > 0


class ChunkRepositoryImpl:
    """ChunkRepository 端口实现（共享内核：Indexing 写、Retrieval 读）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_document(self, document_id: UUID) -> list[Chunk]:
        result = await self.session.execute(
            select(Chunk).where(Chunk.document_id == document_id)
        )
        return list(result.scalars().all())

    async def batch_replace(self, document_id: UUID, chunks: list[dict]) -> int:
        """幂等替换：先删旧 chunk 再批量插入。不 commit（由 UoW 管）。

        chunks 字段：content(必填), summary, hypothetical_questions,
        chunk_type, vector, meta, token_count, chunk_id。
        """
        await self.session.execute(
            delete(Chunk)
            .where(Chunk.document_id == document_id)
            .execution_options(synchronize_session=False)
        )
        for chunk_data in chunks:
            chunk_id = chunk_data.get("chunk_id") or str(uuid.uuid4())
            self.session.add(
                Chunk(
                    id=uuid.UUID(chunk_id) if isinstance(chunk_id, str) else chunk_id,
                    document_id=document_id,
                    content=chunk_data["content"],
                    summary=(chunk_data.get("summary") or "")[:500],
                    hypothetical_questions=chunk_data.get("hypothetical_questions", []),
                    chunk_type=chunk_data.get("chunk_type", "recursive"),
                    vector=chunk_data.get("vector"),
                    meta=chunk_data.get("meta", {}),
                    token_count=chunk_data.get("token_count", 0),
                )
            )
        await self.session.flush()
        return len(chunks)

    async def delete_by_document(self, document_id: UUID) -> int:
        result = await self.session.execute(
            delete(Chunk)
            .where(Chunk.document_id == document_id)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount or 0

    async def hybrid_search(
        self,
        kb_id: UUID,
        query_vector: list[float],
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[Chunk]:
        """混合检索（向量 + BM25 + RRF + rerank）。

        Phase 3 从 core/rag/retriever.py::similarity_search 迁移至此。
        """
        raise NotImplementedError(
            "hybrid_search 将在 Phase 3 从 retriever 迁移至仓储层"
        )


class ConversationRepositoryImpl:
    """ConversationRepository 端口实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(
        self, conv_id: UUID, tenant_id: UUID, user_id: UUID
    ) -> Conversation | None:
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.id == conv_id,
                Conversation.tenant_id == tenant_id,
                Conversation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self, tenant_id: UUID, user_id: UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[Conversation], int]:
        base = select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.user_id == user_id,
        )
        total_result = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = total_result.scalar_one()
        result = await self.session.execute(
            base.order_by(Conversation.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def save(self, conv: Conversation) -> Conversation:
        self.session.add(conv)
        await self.session.flush()
        return conv

    async def delete(self, conv_id: UUID, tenant_id: UUID, user_id: UUID) -> bool:
        result = await self.session.execute(
            delete(Conversation)
            .where(
                Conversation.id == conv_id,
                Conversation.tenant_id == tenant_id,
                Conversation.user_id == user_id,
            )
            .execution_options(synchronize_session=False)
        )
        return (result.rowcount or 0) > 0


class MessageRepositoryImpl:
    """MessageRepository 端口实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_conversation(
        self, conv_id: UUID, limit: int = 20
    ) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def save(self, msg: Message) -> Message:
        self.session.add(msg)
        await self.session.flush()
        return msg


class AgentRunRepositoryImpl:
    """AgentRunRepository 端口实现。

    替代 core/agent/persistence.py 的过程式函数（每函数各自 commit）。
    本实现不 commit，事务由 UoW 统一管理。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_run(self, run: AgentRun) -> AgentRun:
        self.session.add(run)
        await self.session.flush()
        return run

    async def update_run(self, run_id: UUID, **fields: Any) -> None:
        await self.session.execute(
            update(AgentRun).where(AgentRun.id == run_id).values(**fields)
        )

    async def save_step(self, step: AgentStep) -> AgentStep:
        self.session.add(step)
        await self.session.flush()
        return step

    async def update_step(self, step_id: UUID, **fields: Any) -> None:
        await self.session.execute(
            update(AgentStep).where(AgentStep.id == step_id).values(**fields)
        )
