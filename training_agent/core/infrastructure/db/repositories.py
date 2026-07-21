"""领域仓储端口的 SQLAlchemy 异步实现。

设计要点：
- 只 add / flush / execute，不 commit / rollback（事务由 UnitOfWork 管）。
- 端口方法返回 ORM 模型对象（Phase 4 引入独立领域实体 + 映射后替换）。
- 租户隔离：写操作校验 tenant_id，读操作按 tenant_id 过滤。
- hybrid_search 委托至 core/rag/retriever.py::Retriever.similarity_search 引擎
  （Phase 3 落地，不重写检索逻辑，避免影响 RAG 主链路）。
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)
from uuid import UUID

from sqlalchemy import String, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.knowledge_base.aggregates import DocumentStatus
from models.tables import (
    AgentRun,
    AgentStep,
    Chunk,
    Conversation,
    Document,
    KnowledgeBase,
    Message,
)

if TYPE_CHECKING:  # 仅类型检查期引用，运行时零依赖
    from core.rag.retriever import RetrievedChunk


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

    async def list_by_kb_paginated(
        self,
        kb_id: UUID,
        page: int = 1,
        page_size: int = 20,
        q: str | None = None,
        status: str | None = None,
        sort: str = "created_desc",
    ) -> tuple[list[Document], int, dict[str, int]]:
        """列出租户知识库文档（过滤 + 排序 + 分页）。

        返回 (items, total, status_counts)。status_counts 为该 kb 全库状态分布，
        不把 q 纳入 counts（保持反映 KB 整体状态，避免每次搜索重算 4 个 count）。
        """
        # 边界保护
        page = max(1, page)
        allowed_sizes = {10, 25, 50}
        if page_size not in allowed_sizes:
            if page_size > 100:
                page_size = 100
            elif page_size < 10:
                page_size = 10
            else:
                page_size = 10  # 其它非白名单值兜底为 10

        # 基础过滤条件
        base_filters = [Document.knowledge_base_id == kb_id]
        if q:
            base_filters.append(Document.title.ilike(f"%{q}%"))
        if status and status != "all":
            if status == DocumentStatus.READY:
                base_filters.append(Document.status == DocumentStatus.READY)
            elif status == DocumentStatus.ERROR:
                base_filters.append(Document.status == DocumentStatus.ERROR)
            elif status == DocumentStatus.INDEXING:
                base_filters.append(
                    Document.status.in_([DocumentStatus.INDEXING, DocumentStatus.PENDING])
                )
            elif status == DocumentStatus.PENDING:
                base_filters.append(Document.status == DocumentStatus.PENDING)
            # 其它值忽略, 不加 status 条件

        # 排序
        if sort == "created_asc":
            order_by = Document.created_at.asc()
        elif sort == "name_asc":
            order_by = Document.title.asc()
        elif sort == "name_desc":
            order_by = Document.title.desc()
        else:
            order_by = Document.created_at.desc()

        # 查询 items (带 offset/limit)
        items_result = await self.session.execute(
            select(Document)
            .where(*base_filters)
            .order_by(order_by)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(items_result.scalars().all())

        # total = base_filters 下命中条数
        total = await self.session.scalar(
            select(func.count(Document.id)).where(*base_filters)
        ) or 0

        # counts: 该 kb 全库各状态数量
        counts_result = await self.session.execute(
            select(Document.status, func.count(Document.id)).where(
                Document.knowledge_base_id == kb_id
            ).group_by(Document.status)
        )
        status_rows = counts_result.all()

        counts = {
            "all": sum(c for _, c in status_rows),
            "ready": 0,
            "indexing": 0,  # indexing + pending 之和
            "error": 0,
        }
        for s, c in status_rows:
            if s == "ready":
                counts["ready"] += c
            elif s in ("indexing", "pending"):
                counts["indexing"] += c
            elif s == "error":
                counts["error"] += c

        return items, total, counts


class ChunkRepositoryImpl:
    """ChunkRepository 端口实现（共享内核：Indexing 写、Retrieval 读）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_document(self, document_id: UUID) -> list[Chunk]:
        result = await self.session.execute(
            select(Chunk).where(Chunk.document_id == document_id)
        )
        return list(result.scalars().all())

    async def list_by_document_paginated(
        self,
        document_id: UUID,
        page: int = 1,
        page_size: int = 20,
        q: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Chunk], int]:
        """分页查询文档切片，支持状态过滤与关键词（内容 / section_title / chunk_id）搜索。"""
        base_stmt = select(Chunk).where(Chunk.document_id == document_id)

        if status == "indexed":
            base_stmt = base_stmt.where(Chunk.vector.is_not(None))
        elif status == "pending":
            base_stmt = base_stmt.where(Chunk.vector.is_(None))
        elif status == "error":
            # 当前 schema 未单独记录 chunk 级 error，返回空集
            return [], 0

        if q:
            like_q = f"%{q}%"
            base_stmt = base_stmt.where(
                or_(
                    Chunk.content.ilike(like_q),
                    func.cast(Chunk.meta, String).ilike(like_q),
                )
            )

        # 用 func.count() 避免引用外层 Chunk.id 造成与 subquery 的笛卡尔积
        total = (
            await self.session.execute(
                select(func.count()).select_from(base_stmt.subquery())
            )
        ).scalar_one() or 0

        stmt = base_stmt.order_by(Chunk.id.asc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def batch_replace(self, document_id: UUID, chunks: list[dict]) -> int:
        """幂等替换：先删旧 chunk 再批量插入。不 commit（由 UoW 管）。

        chunks 字段：content(必填), summary, hypothetical_questions,
        chunk_type, vector, meta, token_count, chunk_id。

        UUID 一致性铁律：每条 chunk 只生成一次 chunk_id，ORM Chunk 与 lexical_chunks
        必须复用同一个 ID；词法索引异常必须向上抛出由 UoW 回滚，禁止吞掉后继续提交
        "chunk 已写但词法索引缺失"的损坏事务。
        """
        await self.session.execute(
            delete(Chunk)
            .where(Chunk.document_id == document_id)
            .execution_options(synchronize_session=False)
        )
        lexical_chunks: list[tuple] = []
        for chunk_data in chunks:
            # 每条 chunk 只生成一次 chunk_id, ORM 与词法索引复用同一 ID
            raw_id = chunk_data.get("chunk_id")
            if isinstance(raw_id, uuid.UUID):
                chunk_id = raw_id
            elif isinstance(raw_id, str) and raw_id:
                chunk_id = uuid.UUID(raw_id)
            else:
                chunk_id = uuid.uuid4()
            self.session.add(
                Chunk(
                    id=chunk_id,
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
            lexical_chunks.append((
                str(chunk_id),
                (chunk_data.get("meta") or {}).get("title", ""),
                chunk_data["content"],
                chunk_data.get("meta", {}),
            ))
        await self.session.flush()
        # 词法索引重建(同一 UoW 事务): 幂等删旧写新
        from core.rag.lexical_index import index_document_async
        kb_row = await self.session.execute(
            select(Document.knowledge_base_id).where(Document.id == document_id)
        )
        kb_id = kb_row.scalar_one_or_none()
        if kb_id:
            # 词法索引异常必须向上抛出, 由 UoW 回滚整个事务;
            # 禁止吞掉后继续提交"chunk 已写但词法索引缺失"的损坏状态。
            await index_document_async(self.session, document_id, str(kb_id), lexical_chunks)
        return len(chunks)

    async def delete_by_document(self, document_id: UUID) -> int:
        """删除文档的所有 chunk(FK 级联自动清理词法索引)。

        显式清理词法索引若失败必须抛出, 禁止在已 abort 的事务上继续提交。
        chunk_lexical_* 的 ON DELETE CASCADE 是真正的兜底清理。
        """
        from core.rag.lexical_index import delete_by_document_async
        # 显式清理词法索引(失败直接抛出, 由 UoW 回滚); FK 级联为兜底
        await delete_by_document_async(self.session, document_id)
        result = await self.session.execute(
            delete(Chunk)
            .where(Chunk.document_id == document_id)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount or 0

    async def count_by_document(self, document_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count(Chunk.id)).where(Chunk.document_id == document_id)
        )
        return result.scalar_one_or_none() or 0

    async def hybrid_search(
        self,
        kb_id: UUID,
        query_vector: list[float],
        query_text: str = "",
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[RetrievedChunk]:
        """混合检索（向量 + BM25 + RRF + rerank）。

        Phase 3：委托至 core/rag/retriever.py::Retriever.similarity_search 引擎，
        不重写检索逻辑（避免影响 RAG 主链路）。调用方（rag_flow / platform /
        knowledge_tool）仍直接用 Retriever.search()，本方法为端口补充能力，
        供后续 Repository 化检索调用方使用。
        """
        from core.rag.retriever import Retriever

        return await Retriever(self.session).similarity_search(
            query_vector=query_vector,
            kb_id=str(kb_id),
            top_k=top_k,
            threshold=0.2,
            filters=filters,
            query_text=query_text,
            use_rerank=True,
            return_timings=False,
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
