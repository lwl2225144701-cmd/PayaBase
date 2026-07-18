"""KnowledgeBase 领域实体（Phase 4 充实）。

聚合根：KnowledgeBase（含 Document、Chunk 内部实体）。

此前文档状态机 / 进度推导 / 重索引判定散落在三处：
- api/routers/docs.py（进度推导 `min(chunk_count*10,90)`）
- core/infrastructure/db/repositories.py（status 映射 `indexing->in_(...)`）
- core/application/documents/import_document.py（重索引判断 `if status=="ready"`）

本模块将这套业务不变量收拢为 Document 领域对象的方法，使领域规则有唯一归宿。

ORM 映射策略（Python + SQLAlchemy 惯例）：ORM 模型本身即带行为的富模型，
不强行拆独立 dataclass + mapper 层（那是 JPA 思维的反模式）。本模块领域实体
以**纯 dataclass** 形式承载业务规则，通过 `from_orm` / `to_orm_updates` 与 ORM
互转；应用层在需要时构造领域对象、调用其方法做判断，而非在调用方硬编码
status 字符串比较。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID


class DocumentStatus:
    """文档状态常量（单一事实来源，消除各处硬编码字符串）。"""

    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    ERROR = "error"

    # 进行中状态集合（pending + indexing 在 UI 上同属「索引中」tab）
    IN_PROGRESS = (PENDING, INDEXING)


@dataclass
class Document:
    id: UUID
    knowledge_base_id: UUID
    title: str
    file_path: str
    file_type: str
    file_size: int
    status: str = DocumentStatus.PENDING
    chunk_count: int = 0
    progress: int = 0
    file_hash: str | None = None
    source_type: str = "local"
    source_url: str | None = None
    error_message: str | None = None
    indexed_at: datetime | None = None
    created_at: datetime | None = None

    # ---- 状态机不变量 ----
    def is_indexed(self) -> bool:
        return self.status == DocumentStatus.READY

    def is_indexing(self) -> bool:
        return self.status in DocumentStatus.IN_PROGRESS

    def is_failed(self) -> bool:
        return self.status == DocumentStatus.ERROR

    def can_reindex(self) -> bool:
        """可否重索引：已就绪或失败的可重试；进行中不可（避免覆盖）。"""
        return self.status in (DocumentStatus.READY, DocumentStatus.ERROR)

    # ---- 进度推导（收拢 docs.py 散落的 `min(chunk_count*10,90)` 规则）----
    def derive_progress(self) -> int:
        if self.status == DocumentStatus.READY:
            return 100
        if self.status == DocumentStatus.INDEXING:
            return min((self.chunk_count or 0) * 10, 90)
        return 0

    # ---- 状态转换：返回待写入字段 dict，供 Repository / Worker 使用 ----
    def mark_indexing(self) -> dict:
        return {
            "status": DocumentStatus.INDEXING,
            "progress": 0,
            "error_message": None,
        }

    def mark_ready(self, chunk_count: int) -> dict:
        return {
            "status": DocumentStatus.READY,
            "progress": 100,
            "chunk_count": chunk_count,
            "indexed_at": datetime.now(timezone.utc),
        }

    def mark_failed(self, error: str) -> dict:
        return {"status": DocumentStatus.ERROR, "error_message": error}

    # ---- ORM 映射 ----
    @classmethod
    def from_orm(cls, orm) -> Document:
        return cls(
            id=orm.id,
            knowledge_base_id=orm.knowledge_base_id,
            title=orm.title,
            file_path=orm.file_path,
            file_type=orm.file_type,
            file_size=orm.file_size,
            status=orm.status or DocumentStatus.PENDING,
            chunk_count=orm.chunk_count or 0,
            progress=orm.progress or 0,
            file_hash=orm.file_hash,
            source_type=orm.source_type or "local",
            source_url=orm.source_url,
            error_message=orm.error_message,
            indexed_at=orm.indexed_at,
            created_at=orm.created_at,
        )

    def to_orm_updates(self) -> dict:
        return {
            "status": self.status,
            "progress": self.progress,
            "chunk_count": self.chunk_count,
            "file_hash": self.file_hash,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "error_message": self.error_message,
            "indexed_at": self.indexed_at,
        }


@dataclass
class Chunk:
    id: UUID
    document_id: UUID
    content: str
    chunk_type: str = "recursive"
    token_count: int = 0
    summary: str | None = None
    meta: dict = field(default_factory=dict)

    @classmethod
    def from_orm(cls, orm) -> Chunk:
        return cls(
            id=orm.id,
            document_id=orm.document_id,
            content=orm.content,
            chunk_type=orm.chunk_type or "recursive",
            token_count=orm.token_count or 0,
            summary=orm.summary,
            meta=orm.meta or {},
        )


@dataclass
class KnowledgeBase:
    id: UUID
    tenant_id: UUID
    name: str
    embedding_model: str
    description: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_orm(cls, orm) -> KnowledgeBase:
        return cls(
            id=orm.id,
            tenant_id=orm.tenant_id,
            name=orm.name,
            embedding_model=orm.embedding_model,
            description=orm.description,
            created_at=orm.created_at,
        )
