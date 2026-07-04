from datetime import datetime
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Response(BaseModel, Generic[T]):
    code: int = 0
    data: Optional[T] = None
    msg: str = ""


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 20


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class UserInfo(BaseModel):
    id: str
    tenant_id: str
    department_id: Optional[str] = None
    department_name: Optional[str] = None
    hr_user_id: Optional[str] = None
    name: str
    email: str
    role: str = "user"
    is_super_admin: bool = False
    is_training_admin: bool = False
    can_manage_knowledge_bases: bool = False


class DepartmentResponse(BaseModel):
    id: str
    name: str
    code: str


class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 1440


class TokenPayload(BaseModel):
    sub: str
    exp: datetime
    tenant_id: str
    user_id: str
