"""Chat 流式输出数据结构。

原定义在 api/schemas/chat.py，Phase 1 移至 core/chat 以消除 core→api 反向依赖；
api/schemas/chat.py 保留 re-export。
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ChatStreamChunk(BaseModel):
    """单个 SSE 流式块。"""

    content: str
    citations: list[dict] = []
    finished: bool = False
    attachment_used: bool = False
    ppt_task_id: Optional[str] = None  # deprecated, use artifact
    pdf_task_id: Optional[str] = None  # deprecated, use artifact
    artifact: Optional[dict] = None  # {"type": "ppt"|"pdf", "task_id": "..."}
    agent: Optional[dict] = None  # {"run_id": "...", "run_db_id": "...", ...}
    web_search_mode: Optional[str] = None  # "off" | "on" | "ask_pending"
