"""Web search state management for conversations."""

import logging
from typing import Optional

from fastapi.responses import StreamingResponse

from core.chat.stream_types import ChatStreamChunk

logger = logging.getLogger(__name__)

EXPLICIT_SEARCH_KEYWORDS = ("允许联网", "联网搜索", "外部搜索", "网上搜索", "公开信息")


def classify_yes_no(text: str) -> bool:
    """Quick yes/no classification for web search permission responses."""
    text = text.strip().lower()
    no_keywords = ("不用", "不要", "算了", "不必", "不了", "别", "不需要", "no", "不搜", "不查", "没必要", "不用了")
    for kw in no_keywords:
        if kw in text:
            return False
    yes_keywords = ("好", "可以", "嗯", "是的", "对", "搜", "查", "行", "ok", "好的", "好吧", "行吧", "搜搜", "查查", "看看", "开")
    for kw in yes_keywords:
        if kw in text:
            return True
    return False


def process_web_search_explicit_keyword(message: str, conv_meta: dict) -> bool:
    """Detect explicit search keywords in user message.

    Returns True if mode was changed to 'on'.
    """
    if any(kw in message for kw in EXPLICIT_SEARCH_KEYWORDS):
        conv_meta["web_search_mode"] = "on"
        conv_meta.pop("ask_pending", None)
        conv_meta.pop("pending_ask_query", None)
        logger.info(f"[WebSearch] 用户消息含显式关键词，开启联网搜索")
        return True
    return False


async def handle_ask_pending_response(
    message: str,
    conv_meta: dict,
    conv,
    db,
) -> tuple[bool, Optional[StreamingResponse], str]:
    """Handle the case where web_search_mode is ask_pending.

    Returns:
        (handled, streaming_response, new_mode)
    """
    if conv_meta.get("web_search_mode") != "ask_pending":
        return False, None, conv_meta.get("web_search_mode", "off")

    is_yes = classify_yes_no(message)
    if is_yes:
        conv_meta["web_search_mode"] = "on"
        conv_meta.pop("ask_pending", None)
        conv_meta.pop("pending_ask_query", None)
        conv.meta = conv_meta
        db.add(conv)
        await db.commit()

        confirm_text = "好的，已开启联网搜索，请重新提问。"

        from core.chat.conversation_service import save_assistant_message
        await save_assistant_message(
            conversation_id=conv.id,
            content=confirm_text,
            citations=[],
            context={"web_search_mode": "on"},
            token_count=0,
            latency_ms=0,
            db=db,
        )

        async def _yes_gen():
            yield f"data: {ChatStreamChunk(content=confirm_text, citations=[], finished=False, attachment_used=False).model_dump_json()}\n\n"
            yield f"data: {ChatStreamChunk(content='', citations=[], finished=True, attachment_used=False, web_search_mode='on').model_dump_json()}\n\n"
        return True, StreamingResponse(_yes_gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}), "on"
    else:
        conv_meta["web_search_mode"] = "off"
        conv_meta.pop("ask_pending", None)
        conv_meta.pop("pending_ask_query", None)
        conv.meta = conv_meta
        db.add(conv)
        await db.commit()

        decline_text = "好的，如有需要随时让我开启联网搜索。"

        from core.chat.conversation_service import save_assistant_message
        await save_assistant_message(
            conversation_id=conv.id,
            content=decline_text,
            citations=[],
            context={},
            token_count=0,
            latency_ms=0,
            db=db,
        )

        async def _no_gen():
            yield f"data: {ChatStreamChunk(content=decline_text, citations=[], finished=False, attachment_used=False).model_dump_json()}\n\n"
            yield f"data: {ChatStreamChunk(content='', citations=[], finished=True, attachment_used=False, web_search_mode='off').model_dump_json()}\n\n"
        return True, StreamingResponse(_no_gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}), "off"


def process_kb_miss(
    active_kb_id: bool,
    chunks_data: list,
    all_attachments: list,
    web_search_mode: str,
    conv_meta: dict,
    pending_query: str = "",
) -> str:
    """Handle knowledge base miss logic for web_search_mode transitions.

    Returns the updated web_search_mode.
    """
    if not active_kb_id or chunks_data or all_attachments:
        # Reset kb_miss_count when we have results
        if active_kb_id and chunks_data and conv_meta.get("kb_miss_count", 0) > 0:
            conv_meta["kb_miss_count"] = 0
        return web_search_mode

    if web_search_mode == "on":
        return web_search_mode

    miss_count = conv_meta.get("kb_miss_count", 0) + 1
    if miss_count >= 3:
        web_search_mode = "on"
        conv_meta["web_search_mode"] = "on"
        conv_meta["kb_miss_count"] = 0
        conv_meta.pop("ask_pending", None)
        conv_meta.pop("pending_ask_query", None)
        logger.info(f"[WebSearch] 连续{miss_count}次KB miss, 自动开启联网搜索")
    else:
        web_search_mode = "ask_pending"
        conv_meta["web_search_mode"] = "ask_pending"
        conv_meta["kb_miss_count"] = miss_count
        # 记录触发 ask_pending 时的用户问题，便于上下文恢复
        conv_meta["pending_ask_query"] = pending_query or conv_meta.get("pending_ask_query") or ""
        logger.info(f"[WebSearch] KB miss #{miss_count}, 设置 ask_pending, pending_query_len={len(conv_meta['pending_ask_query'])}")

    return web_search_mode


async def save_web_search_meta(conv, conv_meta, db):
    """Persist web search meta changes to DB."""
    conv.meta = conv_meta
    db.add(conv)
    await db.commit()
