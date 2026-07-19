from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)


class DocumentFromSourceRequest(BaseModel):
    source_type: str = Field(..., pattern="^(feishu|google_drive)$")
    url: str = Field(..., min_length=1, max_length=2000)
    title: Optional[str] = Field(None, max_length=500)


class DocumentResponse(BaseModel):
    id: str
    knowledge_base_id: str
    title: str
    file_path: str
    file_type: str
    file_size: int
    status: str
    source_type: str = "local"
    source_url: Optional[str] = None
    chunk_count: int = 0
    indexed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    id: str
    title: str
    file_type: str
    file_size: int
    status: str
    source_type: str = "local"
    chunk_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentStatusCounts(BaseModel):
    """文档状态计数。indexing = indexing + pending 之和, 与前端 tab 语义对齐。"""
    all: int = 0
    ready: int = 0
    indexing: int = 0
    error: int = 0


class DocumentPageResponse(BaseModel):
    """分页文档列表响应。"""
    items: list[DocumentListResponse]
    total: int
    page: int
    page_size: int
    counts: DocumentStatusCounts


class DocumentContentResponse(BaseModel):
    """文档原文（Markdown / 提取文本）预览接口响应。"""

    content: str


class ChunkResponse(BaseModel):
    id: str
    document_id: str
    chunk_id: str | None = None
    content: str
    section_title: str | None = None
    page_number: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    token_count: int = 0
    character_count: int = 0
    vector_status: str = "pending"  # indexed / pending / error
    embedding_model: str | None = None
    created_at: datetime | None = None
    meta: dict = {}

    model_config = {"from_attributes": True}


class ChunkPageResponse(BaseModel):
    """文档切片分页响应。"""

    items: list[ChunkResponse]
    total: int
    page: int
    page_size: int
