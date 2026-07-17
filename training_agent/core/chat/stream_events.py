"""SSE streaming helpers for chat responses."""

import asyncio
import threading
import logging

from core.chat.stream_types import ChatStreamChunk

logger = logging.getLogger(__name__)


async def stream_sync_iterator(sync_iterable):
    """Convert a synchronous iterable to an async iterator via a thread."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[object] = asyncio.Queue()
    sentinel = object()

    def worker():
        try:
            for item in sync_iterable:
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, sentinel)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        item = await queue.get()
        if item is sentinel:
            break
        if isinstance(item, Exception):
            raise item
        yield item


async def stream_llm_response(llm, messages, *, temperature: float):
    """Stream LLM response, converting sync generator to async."""
    async for chunk in stream_sync_iterator(
        llm.stream_chat(messages, temperature=temperature)
    ):
        yield chunk


def format_sse_chunk(
    *,
    content: str = "",
    citations: list = None,
    finished: bool = False,
    attachment_used: bool = False,
    web_search_mode: str = None,
    agent: dict = None,
    artifact: dict = None,
    ppt_task_id: str = None,
    pdf_task_id: str = None,
) -> str:
    """Build a single SSE data: line from ChatStreamChunk."""
    chunk = ChatStreamChunk(
        content=content,
        citations=citations or [],
        finished=finished,
        attachment_used=attachment_used,
        web_search_mode=web_search_mode,
        agent=agent,
        artifact=artifact,
        ppt_task_id=ppt_task_id,
        pdf_task_id=pdf_task_id,
    )
    return f"data: {chunk.model_dump_json()}\n\n"
