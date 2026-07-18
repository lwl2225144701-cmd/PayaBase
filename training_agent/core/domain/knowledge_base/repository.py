"""KnowledgeBase / Document / Chunk 仓储端口。

Chunk 是 KnowledgeBase ↔ Retrieval 的共享内核：
- Indexing 上下文经 ChunkRepository 写入（batch_replace 幂等替换）
- Retrieval 上下文经 ChunkRepository.hybrid_search 读取
统一端口，SQL 沉到基础设施层实现。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:  # 仅类型检查期引用 ORM，运行时零依赖
    from core.rag.retriever import RetrievedChunk
    from models.tables import Chunk, Document, KnowledgeBase


class KnowledgeBaseRepository(Protocol):
    """知识库聚合根仓储。"""

    async def get_by_id(self, kb_id: UUID, tenant_id: UUID) -> KnowledgeBase | None:
        """按 ID + 租户获取知识库（租户隔离）。"""
        ...

    async def list_by_tenant(
        self, tenant_id: UUID, department_id: UUID | None = None
    ) -> list[KnowledgeBase]:
        """列出租户下的知识库，可按部门过滤。"""
        ...

    async def save(self, kb: KnowledgeBase) -> KnowledgeBase:
        """新建或更新知识库。"""
        ...

    async def delete(self, kb_id: UUID, tenant_id: UUID) -> bool:
        """删除知识库（租户隔离校验），返回是否删除成功。"""
        ...


class DocumentRepository(Protocol):
    """文档仓储（KnowledgeBase 聚合内部实体）。"""

    async def get_by_id(self, doc_id: UUID) -> Document | None:
        ...

    async def list_by_kb(self, kb_id: UUID) -> list[Document]:
        ...

    async def save(self, doc: Document) -> Document:
        """新建或更新文档。"""
        ...

    async def update_status(self, doc_id: UUID, status: str, **fields: object) -> None:
        """更新文档状态（pending/indexing/ready/failed）及附带字段。"""
        ...

    async def delete(self, doc_id: UUID) -> bool:
        ...


class ChunkRepository(Protocol):
    """Chunk 共享内核仓储：Indexing 写、Retrieval 读。"""

    async def get_by_document(self, document_id: UUID) -> list[Chunk]:
        """读取某文档的全部 chunk。"""
        ...

    async def batch_replace(self, document_id: UUID, chunks: list[dict]) -> int:
        """幂等替换：先删旧 chunk 再批量插入，返回入库数量。"""
        ...

    async def delete_by_document(self, document_id: UUID) -> int:
        """删除某文档的全部 chunk，返回删除数量。"""
        ...

    async def hybrid_search(
        self,
        kb_id: UUID,
        query_vector: list[float],
        query_text: str = "",
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[RetrievedChunk]:
        """混合检索（向量 + BM25 + RRF + rerank），返回 top_k 带分 chunk。

        query_text 用于 BM25 词频统计；不传则退化为纯向量检索。
        委托至 core/rag/retriever.py::Retriever.similarity_search 引擎，
        不在仓储层重写检索逻辑（避免影响 RAG 主链路）。
        """
        ...
