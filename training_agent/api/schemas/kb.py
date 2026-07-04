from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    department_id: Optional[str] = None
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


class KnowledgeBaseResponse(BaseModel):
    id: str
    tenant_id: str
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    name: str
    description: Optional[str] = None
    embedding_model: str
    doc_count: int = 0
    can_manage: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeBaseListResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    doc_count: int = 0
    can_manage: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}
