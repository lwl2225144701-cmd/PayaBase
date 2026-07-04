"""Chat API routes.

Thin routing layer: validates inputs, dispatches to chat_pipeline, handles errors.
"""

import uuid
import logging
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse

from api.deps import DBSession, CurrentUser
from api.schemas.common import Response
from api.schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    ConversationListResponse,
    ChatRequest,
    MessageResponse,
)
from core.exceptions import NotFoundException, ValidationException
from core.permissions import require_visible_kb
from core.chat.chat_pipeline import handle_chat
from core.chat.conversation_service import (
    list_conversations as svc_list_conversations,
    create_conversation as svc_create_conversation,
    get_conversation_messages,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/conversations", response_model=Response[list[ConversationListResponse]])
async def list_conversations(
    db: DBSession,
    current_user: CurrentUser,
    page: int = 1,
    page_size: int = 20,
):
    items = await svc_list_conversations(db, current_user, page, page_size)
    return Response(data=items)


@router.post("/conversations", response_model=Response[ConversationResponse])
async def create_conversation(
    data: ConversationCreate,
    db: DBSession,
    current_user: CurrentUser,
):
    kb_id = uuid.UUID(data.knowledge_base_id) if data.knowledge_base_id else None
    if kb_id:
        await require_visible_kb(db, current_user, kb_id)
    conv = await svc_create_conversation(data, db, current_user)
    return Response(data=conv)


@router.get("/conversations/{conversation_id}", response_model=Response[list[MessageResponse]])
async def get_conversation(
    conversation_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    messages = await get_conversation_messages(conversation_id, db, current_user)
    return Response(data=messages)


@router.post("/conversations/{conversation_id}/chat")
async def chat_json(
    conversation_id: str,
    data: ChatRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    """Chat endpoint (JSON body, backward compatible, no file)."""
    return await handle_chat(
        conversation_id=conversation_id,
        message=data.message,
        knowledge_base_id_str=data.knowledge_base_id,
        web_search=data.web_search,
        files=[],
        db=db,
        current_user=current_user,
    )


@router.post("/conversations/{conversation_id}/chat/upload")
async def chat_with_attachment(
    conversation_id: str,
    db: DBSession,
    current_user: CurrentUser,
    message: str = Form(...),
    knowledge_base_id: Optional[str] = Form(None),
    web_search: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[]),
):
    """Chat endpoint with file attachments (multipart/form-data)."""
    try:
        return await handle_chat(
            conversation_id=conversation_id,
            message=message,
            knowledge_base_id_str=knowledge_base_id,
            web_search=(web_search == "true") if web_search is not None else None,
            files=files,
            db=db,
            current_user=current_user,
        )
    except NotFoundException as e:
        return JSONResponse(status_code=404, content={"code": 404, "data": None, "msg": e.message})
    except ValidationException as e:
        return JSONResponse(status_code=400, content={"code": 400, "data": None, "msg": e.message})
    except Exception as e:
        logger.error(f"[Chat] 端点异常: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"code": 500, "data": None, "msg": str(e)})
