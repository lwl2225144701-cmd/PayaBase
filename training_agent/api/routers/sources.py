import base64
import hashlib
import json
import logging
import uuid
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from api.deps import DBSession, CurrentUser
from api.routers.docs import _document_response, _persist_document
from api.schemas.common import Response
from api.schemas.doc import DocumentResponse
from api.schemas.sources import (
    FeishuFileItemResponse,
    FeishuFileListRequest,
    FeishuOAuthCallbackResponse,
    FeishuOAuthLoginResponse,
    GoogleDrivePreviewRequest,
    GoogleDrivePreviewResponse,
    SourceUploadToKBRequest,
)
from core.config import settings
from core.exceptions import ValidationException
from core.permissions import require_manage_kb
from core.sources.google_drive import GoogleDriveSource
from core.sources.registry import get_source
from models.tables import Document

logger = logging.getLogger(__name__)

router = APIRouter()

FEISHU_AUTHORIZE_URL = "https://accounts.feishu.cn/open-apis/authen/v1/index"
FEISHU_APP_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"
FEISHU_USER_TOKEN_URL = "https://open.feishu.cn/open-apis/authen/v1/access_token"
FEISHU_USER_INFO_URL = "https://open.feishu.cn/open-apis/authen/v1/user_info"
FEISHU_FILES_URL = "https://open.feishu.cn/open-apis/drive/v1/files"


def _encode_state(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _decode_state(state: str | None) -> dict[str, Any]:
    if not state:
        return {}
    padding = "=" * (-len(state) % 4)
    try:
        raw = base64.urlsafe_b64decode((state + padding).encode("utf-8"))
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _merge_query_params(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({k: v for k, v in params.items() if v is not None})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _validated_redirect_uri(requested_redirect_uri: str | None) -> str:
    if not requested_redirect_uri:
        return ""
    if settings.feishu_oauth_redirect_uri and requested_redirect_uri == settings.feishu_oauth_redirect_uri:
        return requested_redirect_uri
    logger.warning("Ignoring unapproved Feishu redirect_uri")
    return ""


async def _get_feishu_app_access_token(client: httpx.AsyncClient) -> str:
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise ValidationException("飞书应用配置未启用")

    resp = await client.post(
        FEISHU_APP_TOKEN_URL,
        json={"app_id": settings.feishu_app_id, "app_secret": settings.feishu_app_secret},
        timeout=10.0,
    )
    if resp.status_code != 200:
        raise ValidationException(f"飞书应用令牌获取失败: HTTP {resp.status_code}")

    data = resp.json()
    if data.get("code") != 0:
        raise ValidationException(f"飞书应用令牌获取失败: {data.get('msg')}")

    token = data.get("tenant_access_token") or data.get("app_access_token")
    if not token:
        raise ValidationException("飞书应用令牌响应缺少 access_token")
    return token


async def _exchange_feishu_code(code: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        app_access_token = await _get_feishu_app_access_token(client)
        resp = await client.post(
            FEISHU_USER_TOKEN_URL,
            headers={"Authorization": f"Bearer {app_access_token}"},
            json={"grant_type": "authorization_code", "code": code},
            timeout=10.0,
        )
        if resp.status_code != 200:
            raise ValidationException(f"飞书授权码兑换失败: HTTP {resp.status_code}")
        data = resp.json()
        if data.get("code") != 0:
            raise ValidationException(f"飞书授权码兑换失败: {data.get('msg')}")
        token_data = data.get("data", {})
        access_token = token_data.get("access_token")
        if not access_token:
            raise ValidationException("飞书授权码兑换结果缺少 access_token")

        user_info_resp = await client.get(
            FEISHU_USER_INFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
        user_info_data: dict[str, Any] = {}
        if user_info_resp.status_code == 200:
            user_payload = user_info_resp.json()
            if user_payload.get("code") == 0:
                user_info_data = user_payload.get("data", {}) or {}

        return {
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token"),
            "expires_in": token_data.get("expires_in", 0),
            "user_id": token_data.get("user_id") or user_info_data.get("user_id"),
            "open_id": token_data.get("open_id") or user_info_data.get("open_id"),
            "union_id": token_data.get("union_id") or user_info_data.get("union_id"),
            "user_name": user_info_data.get("name") or user_info_data.get("en_name"),
            "email": user_info_data.get("email"),
        }


@router.get("/feishu/login", response_model=Response[FeishuOAuthLoginResponse])
async def feishu_login(request: Request, redirect_uri: str | None = None, scope: str | None = None):
    callback_url = str(request.url_for("feishu_callback"))
    safe_redirect_uri = _validated_redirect_uri(redirect_uri)
    state = _encode_state({"redirect_uri": safe_redirect_uri}) if safe_redirect_uri else ""
    params = {
        "app_id": settings.feishu_app_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": scope or settings.feishu_oauth_scope,
    }
    if state:
        params["state"] = state

    auth_url = f"{FEISHU_AUTHORIZE_URL}?{urlencode(params)}"
    return Response(data=FeishuOAuthLoginResponse(auth_url=auth_url))


@router.get("/feishu/callback", response_model=Response[FeishuOAuthCallbackResponse])
async def feishu_callback(code: str, state: str | None = None, redirect_uri: str | None = None):
    if not code:
        raise ValidationException("缺少飞书授权码 code")

    payload = await _exchange_feishu_code(code)
    target_redirect = _validated_redirect_uri(redirect_uri or _decode_state(state).get("redirect_uri"))

    if target_redirect:
        query = {
            "access_token": payload["access_token"],
            "refresh_token": payload.get("refresh_token") or "",
            "expires_in": str(payload.get("expires_in") or 0),
            "user_id": payload.get("user_id") or "",
            "open_id": payload.get("open_id") or "",
            "union_id": payload.get("union_id") or "",
            "user_name": payload.get("user_name") or "",
            "email": payload.get("email") or "",
        }
        return RedirectResponse(url=_merge_query_params(target_redirect, query), status_code=302)

    return Response(data=FeishuOAuthCallbackResponse(**payload))


@router.post("/feishu/files", response_model=Response[list[FeishuFileItemResponse]])
async def feishu_files(body: FeishuFileListRequest, current_user: CurrentUser):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            FEISHU_FILES_URL,
            params={"page_size": body.page_size},
            headers={"Authorization": f"Bearer {body.access_token}"},
            timeout=20.0,
        )

    if resp.status_code != 200:
        raise ValidationException(f"飞书文档列表获取失败: HTTP {resp.status_code}")

    payload = resp.json()
    if payload.get("code") != 0:
        raise ValidationException(f"飞书文档列表获取失败: {payload.get('msg')}")

    items = payload.get("data", {}).get("files", []) or payload.get("data", {}).get("items", [])
    data = [
        FeishuFileItemResponse(
            id=item.get("token") or item.get("file_token") or item.get("id") or "",
            name=item.get("name") or item.get("title") or "未命名文档",
            url=item.get("url") or None,
        )
        for item in items
        if item.get("token") or item.get("file_token") or item.get("id")
    ]
    return Response(data=data)


@router.post("/google-drive/preview", response_model=Response[GoogleDrivePreviewResponse])
async def google_drive_preview(body: GoogleDrivePreviewRequest, current_user: CurrentUser):
    source = GoogleDriveSource()
    preview = await source.preview(body.url)
    return Response(
        data=GoogleDrivePreviewResponse(
            source_url=preview["source_url"],
            file_id=preview["file_id"],
            file_name=preview["file_name"],
            file_type=preview["file_type"],
            file_size=int(preview["file_size"]),
            content_type=preview.get("content_type"),
        )
    )


@router.post("/upload-to-kb", response_model=Response[DocumentResponse])
async def upload_to_kb(
    body: SourceUploadToKBRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    kb = await require_manage_kb(db, current_user, uuid.UUID(body.kb_id))

    source = get_source(body.source_type)
    if body.source_type == "feishu":
        file_key = body.source_data.get("file_key") or body.source_data.get("url")
        if not file_key:
            raise ValidationException("Feishu source_data 缺少 file_key")
        result = await source.fetch(
            file_key,
            access_token=body.source_data.get("access_token"),
            title=body.title,
            tenant_id=current_user.tenant_id,
        )
    elif body.source_type == "google_drive":
        url = body.source_data.get("url")
        if not url:
            raise ValidationException("Google Drive source_data 缺少 url")
        result = await source.fetch(url, title=body.title)
    else:
        raise ValidationException(f"不支持的 source_type: {body.source_type}")

    file_hash = hashlib.md5(result.content).hexdigest()
    existing_doc = await db.execute(
        select(Document).where(
            Document.knowledge_base_id == kb.id,
            Document.file_hash == file_hash,
        )
    )
    existing = existing_doc.scalar_one_or_none()
    if existing:
        if existing.status == "ready":
            return Response(
                data=_document_response(existing, status_override="already_indexed"),
                msg="文档已存在且已索引完成",
            )
        if existing.status in ("pending", "indexing"):
            return Response(
                data=_document_response(existing),
                msg="文档已在索引中",
            )

    doc = await _persist_document(
        db,
        str(kb.id),
        title=body.title or result.filename,
        storage_filename=result.filename,
        file_content=result.content,
        file_type=result.file_type,
        source_type=result.source_type,
        source_url=result.source_url,
    )

    return Response(
        data=_document_response(doc),
        msg=f"文档已从 {body.source_type} 导入，正在索引",
    )
