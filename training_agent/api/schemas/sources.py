from typing import Any, Optional

from pydantic import BaseModel, Field


class FeishuOAuthLoginResponse(BaseModel):
    auth_url: str


class FeishuOAuthCallbackResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    expires_in: int = 0
    user_id: Optional[str] = None
    open_id: Optional[str] = None
    union_id: Optional[str] = None
    user_name: Optional[str] = None
    email: Optional[str] = None


class FeishuFileListRequest(BaseModel):
    access_token: str = Field(..., min_length=1)
    page_size: int = Field(default=50, ge=1, le=200)


class FeishuFileItemResponse(BaseModel):
    id: str
    name: str
    url: Optional[str] = None


class GoogleDrivePreviewRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2000)


class GoogleDrivePreviewResponse(BaseModel):
    source_url: str
    file_id: str
    file_name: str
    file_type: str
    file_size: int
    content_type: Optional[str] = None


class SourceUploadToKBRequest(BaseModel):
    kb_id: str
    source_type: str = Field(..., pattern="^(feishu|google_drive)$")
    source_data: dict[str, Any] = Field(default_factory=dict)
    title: Optional[str] = Field(None, max_length=500)
