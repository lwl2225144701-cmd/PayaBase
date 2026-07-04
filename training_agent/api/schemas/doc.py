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


class ChunkResponse(BaseModel):
    id: str
    document_id: str
    content: str
    token_count: int
    meta: dict = {}

    model_config = {"from_attributes": True}