from datetime import datetime
from typing import Generic, Optional, TypeVar

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


# UserInfo 已移至 core/domain/identity/user_info.py（消除 core→api 反向依赖）
# 此处 re-export 保持向后兼容
from core.domain.identity.user_info import UserInfo  # noqa: E402,F401


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
