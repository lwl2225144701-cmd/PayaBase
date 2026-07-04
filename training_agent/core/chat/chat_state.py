"""Chat 运行时状态。

将原本散落在 handle_chat 内嵌闭包/外层局部变量里的可变状态收敛到
一个 dataclass,避免使用 nonlocal,且便于在子函数中按引用传递。
"""

import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChatRuntimeState:
    """单次 chat 请求的运行时状态。

    字段保持扁平以兼容现有调用方。所有"会被子函数 / 闭包修改"的变量
    都从原本的外层局部变量迁移到这里,引用传递避免 nonlocal。
    """

    # === 联网搜索 ===
    web_search_mode: str = "off"           # off / on / ask_pending
    conv_meta: dict = field(default_factory=dict)

    # === 知识库 ===
    active_kb_id: Optional[uuid.UUID] = None
    active_kb_name: str = "知识库"

    # === 检索结果 ===
    chunks_data: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)

    # === 输出产物 ===
    artifacts: list[dict] = field(default_factory=list)

    # === 计时 ===
    timings: dict = field(default_factory=dict)

    # === 附件 ===
    attachment_used: bool = False
